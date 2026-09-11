"""Fase 1: los indicadores contra la librería `ta` y contra valores a mano.

Sobre el sembrado de Wilder: RSI, ATR y ADX tienen variantes de suavizado. Acá
se fija **Wilder clásico** (la primera media es simple y de ahí en más recursiva),
que es lo que hacen Wilder en su libro y `ta.rma` de TradingView. `ta` usa ese
mismo sembrado en ATR y ADX pero **no** en RSI, donde arranca la recursión en la
primera variación: por eso el RSI se compara con `ta` después de un burn-in,
cuando la diferencia de sembrado ya se desvaneció, y contra valores calculados a
mano desde la definición.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.indicators import adx, atr, bollinger, ema, macd, rsi, sma, true_range
from tradingbot.indicators.registry import (
    REGISTRY,
    IndicatorError,
    compute_indicator,
    indicator_outputs,
)

ta = pytest.importorskip("ta", reason="`ta` es la referencia para validar indicadores")

TOL = 1e-8


def test_sma_contra_ta(synthetic_df):
    ours, theirs = sma(synthetic_df, 20), ta.trend.sma_indicator(synthetic_df["close"], 20)
    assert np.nanmax(np.abs(ours - theirs)) < TOL


def test_ema_contra_ta(synthetic_df):
    ours, theirs = ema(synthetic_df, 20), ta.trend.ema_indicator(synthetic_df["close"], 20)
    assert np.nanmax(np.abs(ours - theirs)) < TOL


def test_macd_contra_ta(synthetic_df):
    ours = macd(synthetic_df)
    theirs = ta.trend.MACD(synthetic_df["close"])
    assert np.nanmax(np.abs(ours["macd"] - theirs.macd())) < TOL
    assert np.nanmax(np.abs(ours["signal"] - theirs.macd_signal())) < TOL
    assert np.nanmax(np.abs(ours["hist"] - theirs.macd_diff())) < TOL


def test_bollinger_contra_ta(synthetic_df):
    ours = bollinger(synthetic_df, period=20, std=2.0)
    theirs = ta.volatility.BollingerBands(synthetic_df["close"], window=20, window_dev=2)
    assert np.nanmax(np.abs(ours["upper"] - theirs.bollinger_hband())) < TOL
    assert np.nanmax(np.abs(ours["middle"] - theirs.bollinger_mavg())) < TOL
    assert np.nanmax(np.abs(ours["lower"] - theirs.bollinger_lband())) < TOL


def test_atr_contra_ta(synthetic_df):
    ours = atr(synthetic_df, 14)
    theirs = ta.volatility.AverageTrueRange(
        synthetic_df["high"], synthetic_df["low"], synthetic_df["close"], window=14
    ).average_true_range()
    assert np.nanmax(np.abs(ours - theirs)) < TOL


def test_adx_contra_ta(synthetic_df):
    ours = adx(synthetic_df, 14)["adx"]
    theirs = ta.trend.ADXIndicator(
        synthetic_df["high"], synthetic_df["low"], synthetic_df["close"], window=14
    ).adx()
    assert np.nanmax(np.abs(ours - theirs)) < 1e-8


def test_rsi_contra_ta_despues_del_burn_in(synthetic_df):
    """Distinto sembrado, misma recursión: converge a cero exponencialmente."""
    ours = rsi(synthetic_df, 14)
    theirs = ta.momentum.RSIIndicator(synthetic_df["close"], window=14).rsi()
    diff = (ours - theirs).abs()
    assert np.nanmax(diff.iloc[300:]) < 1e-6


# --- valores calculados a mano --------------------------------------------
#: serie de cierres del ejemplo clásico de RSI de 14 períodos
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
    45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
]


def _frame_from_closes(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000] * len(closes),
        },
        index=pd.bdate_range("2020-01-01", periods=len(closes), name="date"),
        dtype="float64",
    )


def test_rsi_valor_publicado_a_mano():
    """Primeras 14 variaciones: ganancias 3.34/14 = 0.2385714, pérdidas 1.40/14 = 0.10.

    RS = 2.3857142857 -> RSI = 100 − 100/(1+RS) = 70.464135.
    """
    df = _frame_from_closes(WILDER_CLOSES)
    values = rsi(df, 14)
    assert values.iloc[:14].isna().all()  # NaN durante el warmup
    assert values.iloc[14] == pytest.approx(70.464135, abs=1e-5)
    # segundo valor, un paso de la recursión de Wilder (la variación es −0.28):
    # avg_gain = 0.2385714 + (0 − 0.2385714)/14 = 0.2215306
    # avg_loss = 0.10 + (0.28 − 0.10)/14 = 0.1128571  -> RSI = 66.249619
    assert values.iloc[15] == pytest.approx(66.249619, abs=1e-5)


def test_atr_valor_a_mano():
    """Con rango constante de 2 y sin gaps, el ATR es exactamente 2."""
    closes = [100.0] * 20
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000] * len(closes),
        },
        index=pd.bdate_range("2020-01-01", periods=len(closes), name="date"),
        dtype="float64",
    )
    values = atr(df, 14)
    assert values.iloc[:13].isna().all()
    assert values.iloc[13] == pytest.approx(2.0)
    assert values.iloc[-1] == pytest.approx(2.0)


def test_true_range_usa_el_cierre_anterior():
    df = pd.DataFrame(
        {
            "open": [100.0, 90.0],
            "high": [101.0, 92.0],
            "low": [99.0, 89.0],
            "close": [100.0, 91.0],
            "volume": [1, 1],
        },
        index=pd.bdate_range("2020-01-01", periods=2, name="date"),
        dtype="float64",
    )
    tr = true_range(df)
    assert tr.iloc[0] == pytest.approx(2.0)
    # gap hacia abajo: |low − close[t-1]| = |89 − 100| = 11 manda sobre high−low = 3
    assert tr.iloc[1] == pytest.approx(11.0)


# --- contrato --------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_contrato_de_cada_indicador(name, synthetic_df):
    """Alineado al índice, con NaN durante el warmup y sin NaN al final."""
    result = compute_indicator(name, synthetic_df, {})
    assert result.index.equals(synthetic_df.index)
    outputs = indicator_outputs(name)
    if outputs:
        assert isinstance(result, pd.DataFrame)
        assert tuple(result.columns) == outputs
        assert result.iloc[-1].notna().all()
    else:
        assert isinstance(result, pd.Series)
        assert result.isna().iloc[0]
        assert pd.notna(result.iloc[-1])


def test_indicador_inexistente_falla_claro(synthetic_df):
    with pytest.raises(IndicatorError, match="desconocido"):
        compute_indicator("supertrend", synthetic_df, {})


def test_parametro_desconocido_falla_claro(synthetic_df):
    with pytest.raises(IndicatorError, match="parámetros desconocidos"):
        compute_indicator("ema", synthetic_df, {"periodo": 20})


def test_macd_rechaza_fast_mayor_que_slow(synthetic_df):
    with pytest.raises(ValueError, match="menor"):
        macd(synthetic_df, fast=26, slow=12)
