"""Cuánto riesgo tiene de verdad cada trade, comparado con el 1R que pide el YAML.

Medido sobre la plantilla ema_cross y el fixture sintético (31 posiciones
abiertas), con ``scripts/riesgo_realizado.py``:

    min 0.539   p05 0.551   media 0.778   mediana 0.787   p95 0.976   max 0.991

Ninguna por encima de 1.00R. El desvío es **sistemáticamente hacia abajo** y
tiene dos causas, ninguna de ellas el gap de la apertura:

* **El tope de concentración** (``max_position_pct: 20``) ata 21 de los 31
  trades, con riesgo medio 0.70R. Con $10.000 de capital, 20% son $2.000, y a
  $545 la acción de SPY eso son 3 acciones: el riesgo queda en la mitad de lo
  declarado mucho antes de que el riesgo sea el límite.
* **El redondeo a acciones enteras**, que con 3 a 13 acciones por posición pesa.
  Aislado (sin el tope), el riesgo va de 0.83R a 1.00R.

El gap **no** desvía el riesgo por acción: el stop se ancla al precio de fill
real, así que la distancia entrada-stop es exactamente 1R siempre. Lo verifica
``test_el_stop_esta_exactamente_a_1r_del_fill``.

Consecuencia práctica: el motor arriesga **menos** de lo que dice el YAML, nunca
más. Es el lado conservador del error, pero significa que "1% por trade" es en
realidad 0.78% promedio sobre esta configuración. Redimensionar en el fill es una
decisión aparte, con el número sobre la mesa.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from tradingbot.backtest.engine import run_backtest
from tradingbot.config import load_strategy


@pytest.fixture(scope="module")
def medicion(request):
    from fixtures.synthetic import synthetic_universe

    from tradingbot.data.validate import validate_ohlcv

    frames = {s: validate_ohlcv(df, s) for s, df in synthetic_universe().items()}
    config = load_strategy("config/strategies/ema_cross.yaml")
    result = run_backtest(config, frames)
    risk_pct = config.risk.position_sizing.risk_pct / 100.0

    filas = []
    for trade in result.trades:
        index = frames[trade.symbol].index
        i = index.get_loc(pd.Timestamp(trade.entry_date))
        equity = float(result.equity.loc[index[i - 1]])
        filas.append(
            {
                "trade": trade,
                "objetivo": equity * risk_pct,
                "r": trade.shares * trade.risk_per_share / (equity * risk_pct),
            }
        )
    return result, pd.DataFrame(filas)


def test_el_riesgo_inicial_nunca_supera_el_objetivo(medicion):
    """La única cota que importa: el motor no puede arriesgar más de lo declarado."""
    _, tabla = medicion
    assert len(tabla) == 31
    assert tabla["r"].max() <= 1.0
    assert (tabla["r"] > 1.0).sum() == 0


def test_la_distribucion_medida_no_se_mueve_sin_que_nos_enteremos(medicion):
    """Fija los números del docstring: si el sizing cambia, este test lo dice."""
    _, tabla = medicion
    r = tabla["r"]
    assert r.min() == pytest.approx(0.539, abs=0.005)
    assert r.mean() == pytest.approx(0.778, abs=0.005)
    assert r.max() == pytest.approx(0.991, abs=0.005)
    assert r.std(ddof=1) == pytest.approx(0.149, abs=0.005)


def test_el_stop_esta_exactamente_a_1r_del_fill(medicion):
    """El gap de la apertura no desvía el riesgo: el stop se ancla al fill real."""
    result, _ = medicion
    for trade in result.trades:
        assert trade.entry_price - trade.stop_initial == pytest.approx(
            trade.risk_per_share, abs=1e-9
        )


def test_quien_ata_el_tamano_es_el_tope_de_concentracion(medicion):
    """21 de 31 posiciones las limita max_position_pct, no el riesgo."""
    result, tabla = medicion
    config = result.config
    frames_por_trade = []
    for fila in tabla.itertuples():
        trade = fila.trade
        por_riesgo = math.floor(fila.objetivo / trade.risk_per_share)
        frames_por_trade.append(trade.shares < por_riesgo)
    assert sum(frames_por_trade) >= 20
    assert config.risk.max_position_pct == 20.0
