"""Las fórmulas de las métricas, contra números calculados a mano."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tradingbot.backtest.metrics import (
    cagr,
    compute_metrics,
    drawdown_series,
    expectancy_r,
    max_drawdown,
    max_drawdown_days,
    profit_factor,
    reliability,
    sharpe,
    top_trades_concentration,
    win_rate,
)
from tradingbot.backtest.portfolio import Trade


def equity(values, start="2020-01-01"):
    return pd.Series(
        values, index=pd.bdate_range(start, periods=len(values), name="date"), dtype="float64"
    )


def trade(pnl: float, pnl_r: float, exit_day: int = 1) -> Trade:
    return Trade(
        symbol="TEST",
        entry_date=pd.Timestamp("2020-01-01").date(),
        entry_price=100.0,
        shares=10,
        risk_per_share=5.0,
        stop_initial=95.0,
        exit_date=(pd.Timestamp("2020-01-01") + pd.Timedelta(days=exit_day)).date(),
        exit_price=100.0 + pnl / 10,
        exit_reasons=["hard_stop" if pnl < 0 else "take_profit"],
        pnl=pnl,
        pnl_r=pnl_r,
        bars_held=5,
        mae_r=-0.5,
        mfe_r=1.5,
        commission=1.0,
        slippage=1.0,
    )


def test_cagr_conocido():
    """Duplicar el capital en 365.25 días es +100% anual."""
    serie = pd.Series(
        [100.0, 200.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-12-31"]),
    )
    dias = (serie.index[-1] - serie.index[0]).days
    esperado = 2.0 ** (365.25 / dias) - 1
    assert cagr(serie) == pytest.approx(esperado)


def test_max_drawdown_y_duracion():
    serie = equity([100, 120, 60, 80, 130])
    assert max_drawdown(serie) == pytest.approx(-0.5)  # de 120 a 60
    assert drawdown_series(serie).iloc[2] == pytest.approx(-0.5)
    # el pico es el día 2 (índice 1) y se recupera el día 5 (índice 4)
    assert max_drawdown_days(serie) == (serie.index[4] - serie.index[1]).days


def test_sharpe_a_mano():
    serie = equity([100, 101, 102, 103])
    rets = serie.pct_change().dropna()
    esperado = rets.mean() / rets.std(ddof=1) * math.sqrt(252)
    assert sharpe(serie) == pytest.approx(esperado)


def test_sharpe_sin_volatilidad_no_explota():
    assert sharpe(equity([100, 100, 100, 100])) == 0.0
    assert sharpe(equity([100])) == 0.0


def test_profit_factor_win_rate_y_expectancy():
    trades = [trade(100, 2.0), trade(-50, -1.0), trade(-50, -1.0), trade(200, 4.0)]
    assert profit_factor(trades) == pytest.approx(300 / 100)
    assert win_rate(trades) == pytest.approx(0.5)
    assert expectancy_r(trades) == pytest.approx((2 - 1 - 1 + 4) / 4)


def test_profit_factor_sin_perdidas_es_infinito():
    assert profit_factor([trade(100, 1.0)]) == float("inf")
    assert profit_factor([]) == 0.0


def test_concentracion_del_resultado():
    ganadores = [trade(100, 1.0) for _ in range(5)]
    resto = [trade(10, 0.1) for _ in range(5)]
    concentracion = top_trades_concentration(ganadores + resto, top=5)
    assert concentracion == pytest.approx(500 / 550)


def test_semaforo_por_cantidad_de_trades():
    assert reliability(12) == "insuficiente"
    assert reliability(50) == "débil"
    assert reliability(150) == "razonable"


def test_racha_de_perdidas_consecutivas():
    trades = [
        trade(-10, -1.0, exit_day=1),
        trade(-10, -1.0, exit_day=2),
        trade(50, 2.0, exit_day=3),
        trade(-10, -1.0, exit_day=4),
        trade(-10, -1.0, exit_day=5),
        trade(-10, -1.0, exit_day=6),
    ]
    assert compute_metrics(equity([100, 110]), trades)["max_consecutive_losses"] == 3


def test_compute_metrics_no_devuelve_nan_ni_infinito_con_serie_normal():
    serie = equity(list(np.linspace(10_000, 12_000, 300)))
    metrics = compute_metrics(serie, [trade(100, 1.0), trade(-50, -1.0)])
    for key, value in metrics.items():
        if isinstance(value, float):
            assert not math.isinf(value), key
    assert metrics["cagr"] > 0
    assert metrics["n_trades"] == 2


def test_sin_trades_no_explota():
    metrics = compute_metrics(equity([10_000] * 10), [])
    assert metrics["n_trades"] == 0
    assert metrics["reliability"] == "insuficiente"
    assert metrics["expectancy_r"] == 0.0
