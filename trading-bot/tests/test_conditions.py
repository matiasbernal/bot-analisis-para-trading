"""Condiciones atómicas y composición all/any/not."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.strategy.conditions import ConditionError, evaluate
from tradingbot.strategy.engine import build_context, evaluate_node

IDX = pd.bdate_range("2020-01-01", periods=6, name="date")


def ctx(**series) -> dict[str, pd.Series]:
    return {k: pd.Series(v, index=IDX, dtype="float64") for k, v in series.items()}


def test_comparaciones_basicas():
    c = ctx(a=[1, 2, 3, 4, 5, 6], b=[3, 3, 3, 3, 3, 3])
    assert evaluate({"left": "a", "op": ">", "right": "b"}, c).tolist() == [
        False, False, False, True, True, True
    ]
    assert evaluate({"left": "a", "op": "<=", "right": 3}, c).tolist() == [
        True, True, True, False, False, False
    ]


def test_crosses_above_es_el_cruce_no_la_desigualdad():
    c = ctx(a=[1, 2, 4, 5, 2, 1], b=[3, 3, 3, 3, 3, 3])
    cruces = evaluate({"left": "a", "op": "crosses_above", "right": "b"}, c)
    assert cruces.tolist() == [False, False, True, False, False, False]


def test_crosses_below():
    c = ctx(a=[5, 4, 2, 1, 4, 5], b=[3, 3, 3, 3, 3, 3])
    cruces = evaluate({"left": "a", "op": "crosses_below", "right": "b"}, c)
    assert cruces.tolist() == [False, False, True, False, False, False]


def test_la_primera_barra_nunca_es_un_cruce():
    c = ctx(a=[9, 1, 1, 1, 1, 1], b=[3, 3, 3, 3, 3, 3])
    assert evaluate({"left": "a", "op": "crosses_above", "right": "b"}, c).iloc[0] is np.False_


def test_nan_de_warmup_nunca_dispara():
    c = ctx(a=[np.nan, np.nan, 5, 5, 5, 5], b=[3, 3, 3, 3, 3, 3])
    result = evaluate({"left": "a", "op": ">", "right": "b"}, c)
    assert result.tolist() == [False, False, True, True, True, True]
    assert result.dtype == bool


def test_between_rising_falling_y_pct_change():
    c = ctx(a=[1, 2, 3, 2, 1, 10])
    assert evaluate({"left": "a", "op": "between", "right": [2, 3]}, c).tolist() == [
        False, True, True, True, False, False
    ]
    assert evaluate({"left": "a", "op": "rising", "right": 1}, c).tolist() == [
        False, True, True, False, False, True
    ]
    assert evaluate({"left": "a", "op": "falling", "right": 1}, c).tolist() == [
        False, False, False, True, True, False
    ]
    # de 1 a 2 es exactamente +100% (no es "mayor que"); de 1 a 10 es +900%
    assert evaluate({"left": "a", "op": "pct_change_gt", "right": 100}, c).tolist() == [
        False, False, False, False, False, True
    ]


def test_composicion_all_any_not():
    c = ctx(a=[1, 2, 3, 4, 5, 6], b=[6, 5, 4, 3, 2, 1])
    nodo = {
        "all": [
            {"left": "a", "op": ">", "right": 2},
            {"any": [{"left": "b", "op": ">", "right": 4}, {"left": "a", "op": ">", "right": 5}]},
        ]
    }
    assert evaluate_node(nodo, c).tolist() == [False, False, False, False, False, True]
    assert evaluate_node({"not": {"left": "a", "op": ">", "right": 2}}, c).tolist() == [
        True, True, False, False, False, False
    ]


def test_operandos_ohlcv_y_constantes(synthetic_df):
    contexto = build_context(synthetic_df, {"ema20": {"type": "ema", "period": 20}})
    assert "close" in contexto and "ema20" in contexto
    resultado = evaluate({"left": "close", "op": ">", "right": "ema20"}, contexto)
    assert resultado.dtype == bool and resultado.any()


def test_indicador_multisalida_se_referencia_con_punto(synthetic_df):
    contexto = build_context(
        synthetic_df, {"bb": {"type": "bollinger", "period": 20}, "macd": {"type": "macd"}}
    )
    assert "bb.upper" in contexto and "bb.lower" in contexto
    # macd declara salida primaria: el alias pelado apunta a la línea macd
    assert "macd" in contexto and "macd.hist" in contexto
    assert "bb" not in contexto  # bollinger no tiene primaria: hay que elegir cuál


def test_errores_claros():
    c = ctx(a=[1, 2, 3, 4, 5, 6])
    with pytest.raises(ConditionError, match="desconocido"):
        evaluate({"left": "a", "op": "cruza_arriba", "right": 1}, c)
    with pytest.raises(ConditionError, match="no existe"):
        evaluate({"left": "ema99", "op": ">", "right": 1}, c)
    with pytest.raises(ConditionError, match="necesita 'right'"):
        evaluate({"left": "a", "op": ">"}, c)
    with pytest.raises(ConditionError, match="no se combinan"):
        evaluate_node({"all": [{"left": "a", "op": ">", "right": 1}], "any": []}, c)
