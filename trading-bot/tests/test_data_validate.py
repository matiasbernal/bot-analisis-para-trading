"""Fase 0: validación del OHLCV. Rechaza cada tipo de dato roto, con mensaje."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fixtures.synthetic import synthetic_ohlcv

from tradingbot.data.validate import DataValidationError, normalize_ohlcv, validate_ohlcv


@pytest.fixture
def raw():
    return synthetic_ohlcv(bars=120)


def test_serie_sana_pasa_y_queda_canonica(raw):
    df = validate_ohlcv(raw, "SYN")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "date" and df.index.tz is None
    assert df.index.is_monotonic_increasing and not df.index.has_duplicates
    assert df["close"].dtype == "float64" and df["volume"].dtype == "int64"
    assert not df.isna().any().any()


def test_normaliza_lo_que_devuelve_yahoo():
    """Columnas capitalizadas, índice tz-aware y columnas de más."""
    index = pd.date_range("2021-01-04", periods=3, freq="B", tz="America/New_York")
    raw = pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [11.0, 12.0, 13.0],
            "Low": [9.0, 10.0, 11.0],
            "Close": [10.5, 11.5, 12.5],
            "Volume": [100, 200, 300],
            "Dividends": [0.0, 0.0, 0.0],
            "Stock Splits": [0.0, 0.0, 0.0],
        },
        index=index,
    )
    df = normalize_ohlcv(raw)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is None
    assert df.index[0] == pd.Timestamp("2021-01-04")


def test_serie_vacia_es_error():
    """yfinance devuelve un DataFrame vacío sin error. Vacío = error, siempre."""
    with pytest.raises(DataValidationError, match="0 velas"):
        validate_ohlcv(pd.DataFrame(), "SYN")


def test_fechas_duplicadas(raw):
    roto = pd.concat([raw, raw.iloc[[10]]]).sort_index()
    with pytest.raises(DataValidationError, match="duplicadas"):
        validate_ohlcv(roto, "SYN")


def test_nan(raw):
    roto = raw.copy()
    roto.iloc[5, roto.columns.get_loc("close")] = np.nan
    with pytest.raises(DataValidationError, match="NaN"):
        validate_ohlcv(roto, "SYN")


def test_high_menor_que_low(raw):
    roto = raw.copy()
    roto.iloc[7, roto.columns.get_loc("high")] = roto["low"].iloc[7] - 1
    with pytest.raises(DataValidationError, match="high < low"):
        validate_ohlcv(roto, "SYN")


def test_close_fuera_del_rango(raw):
    roto = raw.copy()
    roto.iloc[9, roto.columns.get_loc("close")] = roto["high"].iloc[9] + 5
    with pytest.raises(DataValidationError, match="fuera del rango"):
        validate_ohlcv(roto, "SYN")


def test_volumen_cero(raw):
    roto = raw.copy()
    roto.iloc[3, roto.columns.get_loc("volume")] = 0
    with pytest.raises(DataValidationError, match="volumen cero"):
        validate_ohlcv(roto, "SYN")
    # los ETF muy ilíquidos existen: se puede permitir explícitamente
    assert len(validate_ohlcv(roto, "SYN", allow_zero_volume=True)) == len(roto)


def test_salto_de_precio_absurdo(raw):
    """Un salto de 60% sin split: la serie está sin ajustar y el backtest miente."""
    roto = raw.copy()
    col = roto.columns.get_loc("close")
    for i in range(20, len(roto)):
        roto.iloc[i, col] = roto.iloc[i, col] * 2.5
    roto["high"] = roto[["open", "high", "close"]].max(axis=1)
    roto["low"] = roto[["open", "low", "close"]].min(axis=1)
    with pytest.raises(DataValidationError, match="salto de precio"):
        validate_ohlcv(roto, "SYN")


def test_faltan_demasiados_dias_habiles(raw):
    roto = raw.drop(raw.index[30:60])  # 25% de la serie
    with pytest.raises(DataValidationError, match="muy por encima de los feriados"):
        validate_ohlcv(roto, "SYN")


def test_hueco_largo_sin_velas():
    """Pocos días faltantes en total, pero doce seguidos: el feed se cortó."""
    largo = synthetic_ohlcv(bars=400)
    roto = largo.drop(largo.index[100:112])
    with pytest.raises(DataValidationError, match="hueco de 12 días"):
        validate_ohlcv(roto, "SYN")


def test_feriados_normales_no_molestan():
    """Un 3-4% de días hábiles sin vela es el calendario de feriados de US."""
    largo = synthetic_ohlcv(bars=400)
    feriados = largo.index[::30]  # ~3.3%, salteados
    assert len(validate_ohlcv(largo.drop(feriados), "SYN")) == len(largo) - len(feriados)


def test_faltan_columnas(raw):
    with pytest.raises(DataValidationError, match="faltan columnas"):
        validate_ohlcv(raw.drop(columns=["volume"]), "SYN")


def test_el_fixture_sintetico_es_deterministico():
    assert synthetic_ohlcv(bars=50, seed=7).equals(synthetic_ohlcv(bars=50, seed=7))
    assert not synthetic_ohlcv(bars=50, seed=7).equals(synthetic_ohlcv(bars=50, seed=8))
