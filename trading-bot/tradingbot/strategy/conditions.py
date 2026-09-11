"""Condiciones atómicas: ``evaluate(cond, ctx) -> pd.Series[bool]``.

Los lados ``left``/``right`` pueden ser un indicador declarado, una columna
OHLCV o una constante. Toda comparación con NaN (warmup) da ``False``: nunca se
opera sobre un indicador que todavía no es válido.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


class ConditionError(ValueError):
    """Condición mal escrita: operador desconocido, operando inexistente, etc."""


def _cmp(op):
    def run(left: pd.Series, right: pd.Series, **_: Any) -> pd.Series:
        return op(left, right)

    return run


def _crosses_above(left: pd.Series, right: pd.Series, **_: Any) -> pd.Series:
    # la primera barra no tiene anterior: shift deja NaN y la comparación da False
    return (left > right) & (left.shift(1) <= right.shift(1))


def _crosses_below(left: pd.Series, right: pd.Series, **_: Any) -> pd.Series:
    return (left < right) & (left.shift(1) >= right.shift(1))


def _between(left: pd.Series, right: Any, **_: Any) -> pd.Series:
    if not isinstance(right, (list, tuple)) or len(right) != 2:
        raise ConditionError("'between' espera right: [minimo, maximo]")
    low, high = right
    return (left >= low) & (left <= high)


def _rising(left: pd.Series, right: Any = None, *, bars: int = 1, **_: Any) -> pd.Series:
    n = _bars(right, bars)
    return left > left.shift(n)


def _falling(left: pd.Series, right: Any = None, *, bars: int = 1, **_: Any) -> pd.Series:
    n = _bars(right, bars)
    return left < left.shift(n)


def _pct_change_gt(left: pd.Series, right: Any, *, bars: int = 1, **_: Any) -> pd.Series:
    if not isinstance(right, (int, float)) or isinstance(right, bool):
        raise ConditionError("'pct_change_gt' espera right: un número (porcentaje)")
    return left.pct_change(int(bars)) * 100.0 > float(right)


def _bars(right: Any, bars: int) -> int:
    if right is None:
        return int(bars)
    if isinstance(right, (int, float)) and not isinstance(right, bool):
        return int(right)
    raise ConditionError("'rising'/'falling' esperan right: cantidad de barras (número)")


#: operador del YAML -> función. Es la lista cerrada que valida ``config.py``.
OPERATORS: dict[str, Any] = {
    ">": _cmp(lambda a, b: a > b),
    "<": _cmp(lambda a, b: a < b),
    ">=": _cmp(lambda a, b: a >= b),
    "<=": _cmp(lambda a, b: a <= b),
    "==": _cmp(lambda a, b: a == b),
    "crosses_above": _crosses_above,
    "crosses_below": _crosses_below,
    "between": _between,
    "rising": _rising,
    "falling": _falling,
    "pct_change_gt": _pct_change_gt,
}

#: operadores cuyo ``right`` no es una serie sino un parámetro
_RAW_RIGHT = {"between", "rising", "falling", "pct_change_gt"}


def resolve_operand(value: Any, ctx: Mapping[str, pd.Series], index: pd.Index) -> pd.Series:
    """Un nombre del contexto o una constante, siempre como Serie alineada."""
    if isinstance(value, str):
        if value not in ctx:
            raise ConditionError(
                f"operando '{value}' no existe. Disponibles: {', '.join(sorted(ctx))}"
            )
        return ctx[value]
    if isinstance(value, bool):
        raise ConditionError("los booleanos no son operandos válidos")
    if isinstance(value, (int, float, np.integer, np.floating)):
        return pd.Series(float(value), index=index, dtype="float64")
    raise ConditionError(f"operando no soportado: {value!r}")


def evaluate(cond: Mapping[str, Any], ctx: Mapping[str, pd.Series]) -> pd.Series:
    """Evalúa una condición atómica y devuelve una Serie booleana."""
    if not isinstance(cond, Mapping):
        raise ConditionError(f"una condición debe ser un mapeo, llegó {type(cond).__name__}")

    missing = {"left", "op"} - set(cond)
    if missing:
        raise ConditionError(f"la condición {dict(cond)} no tiene {sorted(missing)}")

    op_name = cond["op"]
    if op_name not in OPERATORS:
        raise ConditionError(
            f"operador '{op_name}' desconocido. Disponibles: {', '.join(OPERATORS)}"
        )

    if not ctx:
        raise ConditionError("el contexto está vacío: no hay series sobre las que evaluar")
    index = next(iter(ctx.values())).index

    left = resolve_operand(cond["left"], ctx, index)
    raw_right = cond.get("right")
    extra = {k: v for k, v in cond.items() if k not in {"left", "op", "right"}}

    if op_name in _RAW_RIGHT:
        result = OPERATORS[op_name](left, raw_right, **extra)
    else:
        if raw_right is None:
            raise ConditionError(f"el operador '{op_name}' necesita 'right'")
        result = OPERATORS[op_name](left, resolve_operand(raw_right, ctx, index), **extra)

    return pd.Series(result, index=index).fillna(False).astype(bool)
