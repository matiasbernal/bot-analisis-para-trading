"""Registry de indicadores: ``"ema"`` -> función. Es lo que hace que el YAML funcione.

``config.py`` valida contra este registry que todo ``type:`` exista y que sus
parámetros sean los que la función acepta, **antes** de descargar un solo dato.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

import pandas as pd

from tradingbot.indicators.momentum import rsi
from tradingbot.indicators.trend import adx, ema, macd, sma
from tradingbot.indicators.volatility import atr, bollinger, stdev


class IndicatorError(ValueError):
    """Indicador inexistente, parámetro desconocido o salida inválida."""


#: nombre en el YAML -> función que lo calcula
REGISTRY: dict[str, Callable[..., pd.Series | pd.DataFrame]] = {
    "sma": sma,
    "ema": ema,
    "macd": macd,
    "adx": adx,
    "rsi": rsi,
    "atr": atr,
    "stdev": stdev,
    "bollinger": bollinger,
    "bb": bollinger,
}

#: indicadores de varias salidas: columnas del DataFrame que devuelven
OUTPUTS: dict[str, tuple[str, ...]] = {
    "macd": ("macd", "signal", "hist"),
    "adx": ("adx", "plus_di", "minus_di"),
    "bollinger": ("upper", "middle", "lower", "width"),
    "bb": ("upper", "middle", "lower", "width"),
}

#: columna a la que apunta el alias pelado (``adx`` -> ``adx.adx``).
#: Bollinger no tiene: hay que escribir ``bb.upper`` y decir cuál se quiere.
PRIMARY_OUTPUT: dict[str, str] = {
    "macd": "macd",
    "adx": "adx",
}


def indicator_outputs(type_: str) -> tuple[str, ...]:
    """Columnas que devuelve el indicador; ``()`` si devuelve una sola Serie."""
    return OUTPUTS.get(type_, ())


def primary_output(type_: str) -> str | None:
    """Columna a la que resuelve el alias sin sufijo, si la hay."""
    return PRIMARY_OUTPUT.get(type_)


def get_indicator(type_: str) -> Callable[..., pd.Series | pd.DataFrame]:
    try:
        return REGISTRY[type_]
    except KeyError:
        raise IndicatorError(
            f"indicador '{type_}' desconocido. Disponibles: {', '.join(sorted(REGISTRY))}"
        ) from None


def validate_params(type_: str, params: dict[str, Any]) -> None:
    """Rechaza parámetros que la función del indicador no acepta."""
    func = get_indicator(type_)
    signature = inspect.signature(func)
    accepted = {name for name in signature.parameters if name != "df"}
    unknown = sorted(set(params) - accepted)
    if unknown:
        raise IndicatorError(
            f"indicador '{type_}': parámetros desconocidos {unknown}. "
            f"Acepta: {sorted(accepted)}"
        )


def compute_indicator(
    type_: str, df: pd.DataFrame, params: dict[str, Any] | None = None
) -> pd.Series | pd.DataFrame:
    """Calcula un indicador sobre el OHLCV, validando primero sus parámetros."""
    params = dict(params or {})
    validate_params(type_, params)
    result = get_indicator(type_)(df, **params)
    if not result.index.equals(df.index):
        raise IndicatorError(f"indicador '{type_}': la salida no está alineada al índice")
    return result
