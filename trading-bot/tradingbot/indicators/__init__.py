"""Indicadores técnicos.

Contrato (PLAN.md): ``def ema(df, period: int, source: str = "close") -> pd.Series``,
alineada a ``df.index``, con NaN durante el warmup. Los de varias salidas (MACD,
Bollinger, ADX) devuelven un ``DataFrame`` y el YAML los referencia como
``macd.hist``, ``bb.upper``.

Todo se calcula vectorizado con pandas una sola vez; el loop barra a barra del
backtest corre sobre arrays de numpy.
"""

from tradingbot.indicators.registry import (
    REGISTRY,
    IndicatorError,
    compute_indicator,
    indicator_outputs,
    primary_output,
)
from tradingbot.indicators.momentum import rsi
from tradingbot.indicators.trend import adx, ema, macd, sma
from tradingbot.indicators.volatility import atr, bollinger, true_range, wilder_smooth

__all__ = [
    "REGISTRY",
    "IndicatorError",
    "compute_indicator",
    "indicator_outputs",
    "primary_output",
    "sma",
    "ema",
    "macd",
    "adx",
    "rsi",
    "atr",
    "bollinger",
    "true_range",
    "wilder_smooth",
]
