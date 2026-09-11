"""Sizing: la cuenta exacta y los tres topes, con el motivo cuando no hay trade."""

from __future__ import annotations

import math

import pytest
from conftest import make_strategy
from fixtures.candles import flat, frame

from tradingbot.backtest.engine import run_backtest
from tradingbot.data.validate import validate_ohlcv
from tradingbot.strategy.risk import size_position

BASE = dict(
    equity=10_000.0,
    price=100.0,
    risk_per_share=5.0,
    risk_pct=1.0,
    max_position_pct=100.0,
    cash=10_000.0,
)


def test_formula_basica():
    """floor(10.000 × 1% / 5) = floor(20) = 20 acciones."""
    result = size_position(**BASE)
    assert result.shares == 20
    assert result.reason == "ok"
    assert result.ok


def test_acciones_enteras_sin_fraccionarias():
    result = size_position(**{**BASE, "risk_per_share": 3.0})
    assert result.shares == math.floor(100 / 3) == 33


def test_tope_de_concentracion():
    """Un stop muy ajustado sin tope produce posiciones gigantes."""
    sin_tope = size_position(**{**BASE, "risk_per_share": 0.1})
    assert sin_tope.shares == 100  # limitado por el cash (100 × $100 = $10.000)

    con_tope = size_position(**{**BASE, "risk_per_share": 0.1, "max_position_pct": 20.0})
    assert con_tope.shares == 20
    assert "max_position_pct" in con_tope.reason


def test_tope_por_cash():
    result = size_position(**{**BASE, "risk_per_share": 0.5, "cash": 500.0})
    assert result.shares == 5
    assert "cash" in result.reason


def test_cero_acciones_con_motivo():
    sin_riesgo = size_position(**{**BASE, "risk_per_share": float("nan")})
    assert sin_riesgo.shares == 0 and "ATR" in sin_riesgo.reason

    caro = size_position(**{**BASE, "risk_per_share": 200.0})
    assert caro.shares == 0 and "riesgo por trade" in caro.reason

    sin_cash = size_position(**{**BASE, "cash": 10.0})
    assert sin_cash.shares == 0 and "cash" in sin_cash.reason

    quebrado = size_position(**{**BASE, "equity": 0.0})
    assert quebrado.shares == 0 and "equity" in quebrado.reason


def test_el_riesgo_del_trade_es_el_1_por_ciento_del_equity():
    """La promesa del sizing: perder en el stop cuesta ~1R = risk_pct del equity."""
    bars = flat(6) + [(100.0, 101.0, 90.0, 91.0), (91.0, 92.0, 90.0, 91.0)]
    df = validate_ohlcv(frame(bars), "TEST")
    config = make_strategy(
        universe=["TEST"],
        warmup_bars=4,
        exits={"hard_stop": {"mode": "pct", "pct": 5.0}, "take_profit": None},
        risk={"position_sizing": {"risk_pct": 1.0}, "max_position_pct": 100.0},
    )
    result = run_backtest(config, {"TEST": df})
    trade = result.trades[0]

    assert trade.exit_reasons == ["hard_stop"]
    assert trade.pnl == pytest.approx(-100.0, abs=5.0)  # 1% de $10.000
    assert trade.pnl_r == pytest.approx(-1.0, abs=0.01)


def test_las_senales_rechazadas_quedan_registradas(universe_frames):
    """Si hay más señales que lugares, la de más queda registrada con el motivo."""
    config = make_strategy(
        universe=["AAPL", "MSFT", "SPY", "QQQ"],
        warmup_bars=50,
        indicators={"sma": {"type": "sma", "period": 50}},
        entry={"all": [{"left": "close", "op": ">", "right": "sma"}]},
        exits={"hard_stop": {"mode": "pct", "pct": 5.0}, "take_profit": {"ratio": 3.0}},
        risk={"position_sizing": {"risk_pct": 1.0}, "max_open_positions": 1},
    )
    result = run_backtest(config, universe_frames)
    motivos = {r.reason for r in result.rejections}
    assert result.rejections
    assert "max_open_positions alcanzado" in motivos
    assert len(result.trades) > 0
