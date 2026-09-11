"""Motor de backtest propio: loop barra a barra, costos, métricas y manifiesto."""

from tradingbot.backtest.costs import CostModel
from tradingbot.backtest.engine import BacktestResult, run_backtest
from tradingbot.backtest.portfolio import Portfolio, Trade, buy_and_hold
from tradingbot.backtest.metrics import compute_metrics

__all__ = [
    "CostModel",
    "run_backtest",
    "BacktestResult",
    "Portfolio",
    "Trade",
    "buy_and_hold",
    "compute_metrics",
]
