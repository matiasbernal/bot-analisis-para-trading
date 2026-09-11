"""Indicadores de tendencia: SMA, EMA, MACD y ADX."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingbot.indicators.volatility import true_range, wilder_smooth


def sma(df: pd.DataFrame, period: int = 20, source: str = "close") -> pd.Series:
    """Media móvil simple."""
    return (
        df[source].rolling(window=period, min_periods=period).mean().rename(f"sma_{period}")
    )


def ema(df: pd.DataFrame, period: int = 20, source: str = "close") -> pd.Series:
    """Media móvil exponencial (``adjust=False``, NaN hasta completar el período)."""
    return _ema_series(df[source], period).rename(f"ema_{period}")


def _ema_series(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, min_periods=period, adjust=False).mean()


def macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    source: str = "close",
) -> pd.DataFrame:
    """MACD. Columnas: ``macd``, ``signal``, ``hist``."""
    if fast >= slow:
        raise ValueError("macd: 'fast' debe ser menor que 'slow'")
    line = _ema_series(df[source], fast) - _ema_series(df[source], slow)
    signal_line = _ema_series(line, signal)
    return pd.DataFrame(
        {"macd": line, "signal": signal_line, "hist": line - signal_line},
        index=df.index,
    )


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ADX de Wilder. Columnas: ``adx``, ``plus_di``, ``minus_di``.

    El movimiento direccional se calcula sobre los máximos y mínimos, se suaviza
    con Wilder, y el ADX es el suavizado del DX.
    """
    high, low = df["high"], df["low"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index
    )
    # la primera barra no tiene movimiento direccional definido
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan

    atr_ = wilder_smooth(true_range(df), period)
    plus_di = 100.0 * wilder_smooth(plus_dm, period) / atr_
    minus_di = 100.0 * wilder_smooth(minus_dm, period) / atr_

    denom = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / denom.where(denom != 0, np.nan)
    return pd.DataFrame(
        {"adx": wilder_smooth(dx, period), "plus_di": plus_di, "minus_di": minus_di},
        index=df.index,
    )
