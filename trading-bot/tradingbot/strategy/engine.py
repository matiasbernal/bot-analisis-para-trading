"""Composición de condiciones: ``all`` (AND), ``any`` (OR) y ``not``.

El contexto es un ``dict[str, pd.Series]`` con las columnas OHLCV y cada
indicador declarado en el YAML. Los de varias salidas entran como
``alias.columna`` y, si el indicador declara una salida primaria, también con el
alias pelado.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from tradingbot.data.provider import OHLCV_COLUMNS
from tradingbot.indicators.registry import compute_indicator, primary_output
from tradingbot.strategy.conditions import ConditionError, evaluate


def build_context(
    df: pd.DataFrame, indicators: Mapping[str, Any] | None = None
) -> dict[str, pd.Series]:
    """OHLCV + indicadores calculados, todo alineado al índice del DataFrame."""
    ctx: dict[str, pd.Series] = {
        col: df[col].astype("float64") for col in OHLCV_COLUMNS
    }
    for alias, spec in (indicators or {}).items():
        type_ = getattr(spec, "type", None) or spec["type"]
        params = getattr(spec, "params", None)
        if params is None:
            params = {k: v for k, v in spec.items() if k != "type"}
        result = compute_indicator(type_, df, params)
        if isinstance(result, pd.DataFrame):
            for col in result.columns:
                ctx[f"{alias}.{col}"] = result[col]
            prim = primary_output(type_)
            if prim is not None:
                ctx[alias] = result[prim]
        else:
            ctx[alias] = result
    return ctx


def evaluate_node(node: Mapping[str, Any], ctx: Mapping[str, pd.Series]) -> pd.Series:
    """Evalúa un árbol de condiciones y devuelve una Serie booleana."""
    if not isinstance(node, Mapping):
        raise ConditionError(f"se esperaba un mapeo, llegó {type(node).__name__}")

    combinators = [key for key in ("all", "any", "not") if key in node]
    if len(combinators) > 1:
        raise ConditionError("'all', 'any' y 'not' no se combinan en el mismo nivel")

    if combinators:
        key = combinators[0]
        if key == "not":
            return ~evaluate_node(node["not"], ctx)
        children = node[key]
        if not isinstance(children, list) or not children:
            raise ConditionError(f"'{key}' espera una lista con al menos una condición")
        series = [evaluate_node(child, ctx) for child in children]
        combined = series[0]
        for other in series[1:]:
            combined = combined & other if key == "all" else combined | other
        return combined

    return evaluate(node, ctx)


def signals_for(
    entry: Mapping[str, Any],
    exit_signal: Mapping[str, Any] | None,
    ctx: Mapping[str, pd.Series],
) -> pd.DataFrame:
    """Señales de entrada y de salida por regla, evaluadas al cierre de cada vela."""
    index = next(iter(ctx.values())).index
    entries = evaluate_node(entry, ctx)
    exits = (
        evaluate_node(exit_signal, ctx)
        if exit_signal is not None
        else pd.Series(False, index=index)
    )
    return pd.DataFrame({"entry": entries, "exit_signal": exits}, index=index)
