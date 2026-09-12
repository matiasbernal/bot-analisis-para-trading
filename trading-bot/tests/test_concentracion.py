"""La concentración del resultado, calibrada contra la cantidad de ganadores.

El porcentaje crudo (5 mejores / ganancia bruta) no se puede comparar contra un
umbral fijo: con 6 ganadores los 5 mejores son el 98% por pura aritmética y con
50 son el 32%. Un umbral de 80% salta siempre en el primer caso y nunca en el
segundo, así que mide cuántos trades hay y no si el resultado está concentrado.

La referencia es la exponencial —la cola "normal" de una serie de ganancias— y
tiene forma cerrada. Este archivo verifica la fórmula contra una simulación, y
fija el comportamiento del aviso.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.backtest.metrics import (
    CONCENTRATION_ALERT,
    MIN_WINNERS_FOR_CONCENTRATION,
    concentration_baseline,
    concentration_ratio,
    top_trades_concentration,
)
from tradingbot.backtest.portfolio import Trade

#: corridas de la simulación que verifica la fórmula cerrada
SIMULACIONES = 20_000

#: tolerancia del cotejo fórmula/simulación: el error de Monte Carlo con 20.000
#: corridas es del orden de 0.002, así que 0.01 deja margen sin volverse inútil
TOLERANCIA = 0.01


def trade(pnl: float, dia: int = 1) -> Trade:
    return Trade(
        symbol="TEST",
        entry_date=pd.Timestamp("2020-01-01").date(),
        entry_price=100.0,
        shares=10,
        risk_per_share=10.0,
        stop_initial=90.0,
        exit_date=(pd.Timestamp("2020-01-01") + pd.Timedelta(days=dia)).date(),
        exit_price=100.0 + pnl / 10,
        exit_reasons=["take_profit" if pnl > 0 else "hard_stop"],
        pnl=pnl,
        pnl_r=pnl / 100,
        bars_held=5,
        mae_r=-0.5,
        mfe_r=1.5,
        commission=0.0,
        slippage=0.0,
    )


def _simular(n: int, top: int = 5, seed: int = 7) -> float:
    """Media de (top mejores / total) sobre ``n`` exponenciales iid."""
    rng = np.random.default_rng(seed)
    muestras = np.sort(rng.exponential(1.0, (SIMULACIONES, n)), axis=1)[:, ::-1]
    return float((muestras[:, :top].sum(axis=1) / muestras.sum(axis=1)).mean())


# --- la fórmula cerrada contra la simulación -------------------------------
def test_la_formula_cerrada_coincide_con_la_simulacion_en_12():
    """El caso del informe: baseline(12) = 0.758 y la simulación da 0.759.

    baseline(n, k) = Σ_{j=1..k} Σ_{m=j..n} (1/m) / n
    Con n=12, k=5:
      j=1: H12          = 3.103211
      j=2: H12 − 1      = 2.103211
      j=3: j=2 − 1/2    = 1.603211
      j=4: j=3 − 1/3    = 1.269877
      j=5: j=4 − 1/4    = 1.019877
      suma = 9.099387  ->  /12 = 0.758282
    """
    esperado = 0.758282
    assert concentration_baseline(12) == pytest.approx(esperado, abs=1e-5)
    assert concentration_baseline(12) == pytest.approx(_simular(12), abs=TOLERANCIA)


@pytest.mark.parametrize("n", [6, 8, 10, 12, 15, 20, 30, 50])
def test_la_formula_cerrada_coincide_con_la_simulacion(n):
    assert concentration_baseline(n) == pytest.approx(_simular(n), abs=TOLERANCIA)


def test_la_baseline_baja_con_la_cantidad_de_ganadores():
    valores = [concentration_baseline(n) for n in (6, 10, 20, 50)]
    assert valores == sorted(valores, reverse=True)
    assert concentration_baseline(5) == 1.0  # cinco ganadores: los 5 mejores son todo
    assert concentration_baseline(3) == 1.0
    assert np.isnan(concentration_baseline(0))


# --- el cociente que se muestra --------------------------------------------
def test_el_cociente_normaliza_por_la_cantidad_de_ganadores():
    """Doce ganadores repartidos parejo dan menos que lo normal, no más."""
    parejos = [trade(100.0, dia=i) for i in range(1, 13)]
    observado = top_trades_concentration(parejos)
    assert observado == pytest.approx(5 / 12)          # todos iguales: 5 de 12
    assert concentration_ratio(parejos) == pytest.approx(5 / 12 / 0.758282, abs=1e-4)
    assert concentration_ratio(parejos) < 1.0


def test_un_resultado_concentrado_da_cociente_alto():
    """Dos trades enormes y diez chicos: eso sí es concentración."""
    concentrado = [trade(10_000.0, dia=1), trade(8_000.0, dia=2)]
    concentrado += [trade(10.0, dia=i) for i in range(3, 13)]
    assert top_trades_concentration(concentrado) > 0.99
    assert concentration_ratio(concentrado) > CONCENTRATION_ALERT


def test_sin_ganadores_el_cociente_es_nan():
    assert np.isnan(concentration_ratio([trade(-100.0)]))


# --- el aviso ---------------------------------------------------------------
def _aviso(trades):
    from types import SimpleNamespace

    from tradingbot.backtest.metrics import compute_metrics
    from tradingbot.reporting.report import _concentration_warning

    equity = pd.Series(
        [10_000.0, 10_100.0], index=pd.bdate_range("2020-01-01", periods=2)
    )
    result = SimpleNamespace(metrics=compute_metrics(equity, trades))
    return _concentration_warning(result)


def test_con_pocos_ganadores_dice_que_no_se_puede_evaluar():
    pocos = [trade(100.0, dia=i) for i in range(1, 7)]  # 6 ganadores
    avisos = _aviso(pocos)
    assert len(avisos) == 1
    assert "no se puede evaluar la concentración" in avisos[0]["text"]
    assert "6 trades ganadores" in avisos[0]["text"]


def test_con_suficientes_ganadores_y_reparto_normal_no_avisa():
    normales = [trade(100.0 + i * 7, dia=i) for i in range(1, 15)]  # 14 ganadores
    assert _aviso(normales) == []


def test_con_suficientes_ganadores_y_concentracion_real_avisa():
    concentrado = [trade(10_000.0, dia=1), trade(9_000.0, dia=2), trade(8_000.0, dia=3)]
    concentrado += [trade(5.0, dia=i) for i in range(4, 16)]  # 15 ganadores
    avisos = _aviso(concentrado)
    assert len(avisos) == 1
    assert "lo normal para 15 ganadores" in avisos[0]["text"]
    assert "× lo normal" in avisos[0]["text"]


def test_el_umbral_del_aviso_esta_donde_dice():
    assert MIN_WINNERS_FOR_CONCENTRATION == 10
    assert CONCENTRATION_ALERT == 1.15
