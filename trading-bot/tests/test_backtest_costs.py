"""Comisión y slippage en cada entrada y en cada salida.

Un backtest sin costos es un folleto. Estos tests verifican el número exacto,
no que "baje un poco".
"""

from __future__ import annotations

import pytest
from conftest import make_strategy
from fixtures.candles import flat, frame

from tradingbot.backtest.costs import CostModel
from tradingbot.backtest.engine import run_backtest
from tradingbot.data.validate import validate_ohlcv

WARMUP = 5


def _run(bars, **execution):
    df = validate_ohlcv(frame(bars), "TEST")
    config = make_strategy(
        warmup_bars=WARMUP - 1, universe=["TEST"], execution=execution or {}
    )
    return run_backtest(config, {"TEST": df})


BARS_UN_TRADE = flat(WARMUP + 1) + [
    (100.0, 120.0, 99.0, 118.0),  # toca el objetivo 115
    (118.0, 119.0, 117.0, 118.0),
]


def test_modelo_de_costos_unitario():
    costs = CostModel(commission_pct=0.1, slippage_pct=0.05)
    assert costs.buy_fill(100.0) == pytest.approx(100.05)
    assert costs.sell_fill(100.0) == pytest.approx(99.95)
    assert costs.commission(100.0, 10) == pytest.approx(1.0)
    assert costs.slippage_cost(100.0, 100.05, 10) == pytest.approx(0.5)
    assert CostModel().free


def test_los_costos_se_aplican_en_las_dos_puntas():
    result = _run(BARS_UN_TRADE, commission_pct=0.1, slippage_pct=0.05)
    trade = result.trades[0]

    # entrada: apertura 100 + 0.05% de slippage
    assert trade.entry_price == pytest.approx(100.05)
    # el objetivo se ancla al precio REAL de entrada: 100.05 + 3 × 1R (1R = 5)
    objetivo = trade.entry_price + 3 * trade.risk_per_share
    assert objetivo == pytest.approx(115.05)
    # salida: objetivo − 0.05% de slippage
    assert trade.exit_price == pytest.approx(objetivo * 0.9995)

    comision_esperada = (
        trade.entry_price * trade.shares * 0.001 + trade.exit_price * trade.shares * 0.001
    )
    assert trade.commission == pytest.approx(comision_esperada)

    slippage_esperado = (
        abs(trade.entry_price - 100.0) * trade.shares
        + abs(objetivo - trade.exit_price) * trade.shares
    )
    assert trade.slippage == pytest.approx(slippage_esperado)


def test_el_pnl_descuenta_la_comision():
    result = _run(BARS_UN_TRADE, commission_pct=0.1, slippage_pct=0.05)
    trade = result.trades[0]
    bruto = (trade.exit_price - trade.entry_price) * trade.shares
    assert trade.pnl == pytest.approx(bruto - trade.commission)
    assert trade.pnl < bruto


def test_con_costos_se_gana_menos_que_sin_costos():
    sin = _run(BARS_UN_TRADE)
    con = _run(BARS_UN_TRADE, commission_pct=0.1, slippage_pct=0.05)
    assert con.metrics["final_equity"] < sin.metrics["final_equity"]
    assert sin.metrics["total_commission"] == 0.0
    assert con.metrics["total_commission"] > 0.0


def test_la_equity_final_coincide_con_el_cash_y_los_costos():
    """Equity final = capital inicial + P&L neto de todos los trades."""
    result = _run(BARS_UN_TRADE, commission_pct=0.1, slippage_pct=0.05)
    esperado = result.config.backtest.initial_cash + sum(t.pnl for t in result.trades)
    assert result.metrics["final_equity"] == pytest.approx(esperado)


def test_un_stop_cuesta_mas_de_1r_por_los_costos(universe_frames):
    """Con costos, perder en el stop cuesta un poco más de 1R. Tiene que notarse."""
    config = make_strategy(
        universe=["SPY"],
        warmup_bars=200,
        indicators={
            "ema_fast": {"type": "ema", "period": 20},
            "ema_slow": {"type": "ema", "period": 50},
        },
        entry={"all": [{"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}]},
        exits={"hard_stop": {"mode": "atr", "multiple": 2.0}, "take_profit": {"ratio": 3.0}},
        execution={"commission_pct": 0.05, "slippage_pct": 0.05},
    )
    result = run_backtest(config, {"SPY": universe_frames["SPY"]})
    stops = [t for t in result.trades if t.exit_reasons == ["hard_stop"]]
    assert stops, "no hubo salidas por stop: el test no prueba nada"
    for trade in stops:
        assert -1.10 < trade.pnl_r < -1.0
        assert trade.commission > 0 and trade.slippage > 0
