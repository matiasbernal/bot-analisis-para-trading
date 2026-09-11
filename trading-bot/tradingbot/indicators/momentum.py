"""Indicadores de momentum: RSI."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingbot.indicators.volatility import wilder_smooth


def rsi(df: pd.DataFrame, period: int = 14, source: str = "close") -> pd.Series:
    """RSI de Wilder (suavizado sembrado con la media de las primeras N variaciones)."""
    diff = df[source].diff()
    gains = diff.clip(lower=0.0)
    losses = (-diff).clip(lower=0.0)
    # la primera fila no tiene variación: queda fuera del sembrado
    gains.iloc[0] = np.nan
    losses.iloc[0] = np.nan

    avg_gain = wilder_smooth(gains, period)
    avg_loss = wilder_smooth(losses, period)

    rs = avg_gain / avg_loss.where(avg_loss != 0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # pérdida media 0 => RSI 100 (no hay división por cero que valga)
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(avg_gain.notna() & avg_loss.notna(), np.nan)
    return out.rename(f"rsi_{period}")
