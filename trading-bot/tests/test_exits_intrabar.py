"""Resolución intrabar de las salidas, con velas escritas a mano.

Las reglas que se prueban acá son las que separan un backtest honesto de uno que
asume que siempre te sacan al precio que querías:

* si la vela abre con gap por debajo del stop, el fill es en la **apertura**;
* si en la misma vela se tocan stop y objetivo, **gana el stop**;
* sin trailing configurado, el stop del trade es el inicial y no se mueve nunca.

El trailing tiene sus propios tests en ``test_trailing_chandelier.py``: acá se
verifica que **sin** la capa nada se mueva, que es la contraparte necesaria.
"""

from __future__ import annotations

import pytest
from conftest import make_strategy
from fixtures.candles import flat, frame

from tradingbot.backtest.engine import run_backtest
from tradingbot.data.validate import validate_ohlcv
from tradingbot.strategy.exits import resolve_intrabar_exit
from tradingbot.strategy.position import Position

WARMUP = 5


def _run(bars, **overrides):
    """Entrada forzada: señal en la barra WARMUP-1, fill en la apertura de WARMUP.

    Con ``hard_stop pct=5`` sobre un cierre de 100, 1R = 5 y el stop queda en 95;
    con ``take_profit rr=3`` el objetivo queda en 115.
    """
    df = validate_ohlcv(frame(bars), "TEST")
    config = make_strategy(warmup_bars=WARMUP - 1, universe=["TEST"], **overrides)
    return run_backtest(config, {"TEST": df}), df


def test_gap_por_debajo_del_stop_llena_en_la_apertura():
    bars = flat(WARMUP + 1) + [
        (90.0, 92.0, 88.0, 91.0),  # abre en 90, muy por debajo del stop de 95
        (91.0, 92.0, 90.0, 91.0),
    ]
    result, _ = _run(bars)
    trade = result.trades[0]

    assert trade.exit_reasons == ["gap_stop"]
    assert trade.exit_price == pytest.approx(90.0)  # la apertura, no el stop
    assert trade.exit_price < trade.stop_initial


def test_stop_y_objetivo_en_la_misma_vela_gana_el_stop():
    bars = flat(WARMUP + 1) + [
        (100.0, 120.0, 94.0, 110.0),  # toca el objetivo 115 y el stop 95
        (110.0, 111.0, 109.0, 110.0),
    ]
    result, _ = _run(bars)
    trade = result.trades[0]

    assert trade.exit_reasons == ["hard_stop"]
    assert trade.exit_price == pytest.approx(95.0)
    assert trade.pnl < 0


def test_objetivo_solo_sale_al_objetivo():
    bars = flat(WARMUP + 1) + [
        (100.0, 120.0, 99.0, 118.0),  # toca 115 sin tocar 95
        (118.0, 119.0, 117.0, 118.0),
    ]
    result, _ = _run(bars)
    trade = result.trades[0]

    assert trade.exit_reasons == ["take_profit"]
    assert trade.exit_price == pytest.approx(115.0)
    assert trade.pnl_r == pytest.approx(3.0, abs=1e-9)


def test_el_hard_stop_no_se_mueve_durante_el_trade():
    """Sin `exits.trailing_stop` en el YAML, el stop del trade es el inicial, siempre."""
    bars = flat(WARMUP + 1) + [
        (100.0, 112.0, 99.5, 111.0),  # sube fuerte pero no llega al objetivo
        (111.0, 113.0, 94.0, 96.0),   # y después se da vuelta hasta el stop
        (96.0, 97.0, 95.0, 96.0),
    ]
    result, _ = _run(bars)
    trade = result.trades[0]

    assert trade.exit_reasons == ["hard_stop"]
    assert trade.exit_price == pytest.approx(95.0)
    assert trade.stop_initial == pytest.approx(95.0)


def test_la_barra_de_entrada_no_dispara_salida_por_gap():
    """Se entra en la apertura: el gap de esa vela ya pasó antes de la compra."""
    bars = flat(WARMUP) + [
        (100.0, 101.0, 99.0, 100.0),   # barra de la señal
        (100.0, 101.0, 99.5, 100.5),   # barra de la entrada
        (100.5, 101.0, 100.0, 100.5),
    ]
    result, _ = _run(bars)
    assert result.trades, "no se abrió ninguna posición: el test no prueba nada"
    assert result.trades[0].exit_reasons == ["fin_del_backtest"]


def test_prioridad_intrabar_unitaria():
    """La función de prioridad, aislada del motor."""
    position = Position(
        symbol="TEST",
        entry_date=None,
        entry_price=100.0,
        shares=10,
        risk_per_share=5.0,
        stop_current=95.0,
        peak_price=100.0,
        target_price=115.0,
    )

    gap = resolve_intrabar_exit(position, bar_open=90.0, bar_high=120.0, bar_low=85.0)
    assert gap.reason == "gap_stop" and gap.price == 90.0

    ambos = resolve_intrabar_exit(position, bar_open=100.0, bar_high=120.0, bar_low=94.0)
    assert ambos.reason == "hard_stop" and ambos.price == 95.0

    objetivo = resolve_intrabar_exit(position, bar_open=100.0, bar_high=120.0, bar_low=99.0)
    assert objetivo.reason == "take_profit" and objetivo.price == 115.0

    ninguno = resolve_intrabar_exit(position, bar_open=100.0, bar_high=110.0, bar_low=99.0)
    assert ninguno is None

    entrada = resolve_intrabar_exit(
        position, bar_open=90.0, bar_high=99.0, bar_low=96.0, opened_this_bar=True
    )
    assert entrada is None
