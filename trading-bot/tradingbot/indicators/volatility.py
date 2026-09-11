"""Indicadores de volatilidad: ATR (Wilder), Bollinger y el suavizado de Wilder."""

from __future__ import annotations

import numpy as np
import pandas as pd


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Suavizado de Wilder (RMA) sembrado con la media simple de las primeras N.

    Es la variante que usan Wilder en su libro y ``ta.rma`` de TradingView:
    ``rma[n-1] = mean(x[0..n-1])`` y después ``rma[t] = rma[t-1] + (x[t] - rma[t-1])/n``.
    Fijar el sembrado importa: la variante recursiva desde la primera barra da
    valores distintos durante cientos de velas.
    """
    if period < 1:
        raise ValueError("period debe ser >= 1")

    values = series.to_numpy(dtype="float64")
    out = np.full(values.shape, np.nan, dtype="float64")

    valid = ~np.isnan(values)
    if valid.sum() < period:
        return pd.Series(out, index=series.index, name=series.name)

    first = int(np.argmax(valid))  # primera posición no-NaN
    seed_end = first + period
    if seed_end > len(values):
        return pd.Series(out, index=series.index, name=series.name)

    prev = float(np.mean(values[first:seed_end]))
    out[seed_end - 1] = prev
    alpha = 1.0 / period
    for i in range(seed_end, len(values)):
        prev = prev + alpha * (values[i] - prev)
        out[i] = prev
    return pd.Series(out, index=series.index, name=series.name)


def true_range(df: pd.DataFrame) -> pd.Series:
    """True range: max(high-low, |high-close[t-1]|, |low-close[t-1]|)."""
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    tr = ranges.max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr.rename("tr")


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range con suavizado de Wilder."""
    return wilder_smooth(true_range(df), period).rename("atr")


def stdev(df: pd.DataFrame, period: int = 20, source: str = "close") -> pd.Series:
    """Desvío estándar poblacional (ddof=0), que es el que usan las bandas."""
    return (
        df[source]
        .rolling(window=period, min_periods=period)
        .std(ddof=0)
        .rename("stdev")
    )


def bollinger(
    df: pd.DataFrame,
    period: int = 20,
    source: str = "close",
    std: float = 2.0,
) -> pd.DataFrame:
    """Bandas de Bollinger. Columnas: ``upper``, ``middle``, ``lower``, ``width``."""
    middle = df[source].rolling(window=period, min_periods=period).mean()
    dev = df[source].rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + std * dev
    lower = middle - std * dev
    return pd.DataFrame(
        {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "width": (upper - lower) / middle,
        },
        index=df.index,
    )
