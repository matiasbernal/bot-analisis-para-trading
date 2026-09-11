"""Métricas del informe, sin ambigüedad (las fórmulas están fijadas en PLAN.md).

Retornos diarios de la curva de equity; Sharpe = media/desvío × √252 con tasa
libre de riesgo 0; Sortino igual pero con el desvío de los negativos;
CAGR = (E_fin/E_ini)^(365.25/días) − 1; MDD sobre el máximo acumulado;
Calmar = CAGR/|MDD|; Profit Factor = suma ganancias / suma pérdidas;
Expectancy = media de ``pnl_r``.

Más las tres cosas que un informe honesto muestra aunque duelan: cantidad de
trades como semáforo, concentración del resultado en los 5 mejores, y racha
máxima de pérdidas consecutivas.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from tradingbot.backtest.portfolio import Trade

PERIODS_PER_YEAR = 252


def daily_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    start_value, end_value = float(equity.iloc[0]), float(equity.iloc[-1])
    if start_value <= 0 or end_value <= 0:
        return float("nan")
    days = (equity.index[-1] - equity.index[0]).days
    if days <= 0:
        return 0.0
    return (end_value / start_value) ** (365.25 / days) - 1.0


def sharpe(equity: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    rets = daily_returns(equity)
    if len(rets) < 2:
        return 0.0
    std = float(rets.std(ddof=1))
    if std == 0 or math.isnan(std):
        return 0.0
    return float(rets.mean()) / std * math.sqrt(periods_per_year)


def sortino(equity: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    rets = daily_returns(equity)
    if len(rets) < 2:
        return 0.0
    downside = rets[rets < 0]
    if len(downside) < 2:
        return 0.0
    std = float(downside.std(ddof=1))
    if std == 0 or math.isnan(std):
        return 0.0
    return float(rets.mean()) / std * math.sqrt(periods_per_year)


def drawdown_series(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    return equity / peak - 1.0


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float(drawdown_series(equity).min())


def max_drawdown_days(equity: pd.Series) -> int:
    """Días corridos del drawdown más largo (desde el pico hasta recuperarlo)."""
    if equity.empty:
        return 0
    peak_value = float(equity.iloc[0])
    peak_date = equity.index[0]
    worst = 0
    for when, value in equity.items():
        # el día que recupera el pico cierra el drawdown, y esa distancia cuenta
        worst = max(worst, (when - peak_date).days)
        if value >= peak_value:
            peak_value, peak_date = float(value), when
    return int(worst)


def profit_factor(trades: Sequence[Trade]) -> float:
    gains = sum(t.pnl for t in trades if t.pnl > 0)
    losses = -sum(t.pnl for t in trades if t.pnl < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def expectancy_r(trades: Sequence[Trade]) -> float:
    if not trades:
        return 0.0
    return float(np.mean([t.pnl_r for t in trades]))


def win_rate(trades: Sequence[Trade]) -> float:
    if not trades:
        return 0.0
    return sum(1 for t in trades if t.pnl > 0) / len(trades)


def win_loss_ratio(trades: Sequence[Trade]) -> float:
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [-t.pnl for t in trades if t.pnl < 0]
    if not wins or not losses:
        return 0.0
    return float(np.mean(wins) / np.mean(losses))


def max_consecutive_losses(trades: Sequence[Trade]) -> int:
    """Lo que vas a tener que aguantar en vivo. Mejor saberlo antes."""
    worst = run = 0
    for trade in sorted(trades, key=lambda t: (t.exit_date, t.symbol)):
        run = run + 1 if trade.pnl < 0 else 0
        worst = max(worst, run)
    return worst


def top_trades_concentration(trades: Sequence[Trade], top: int = 5) -> float:
    """Qué fracción del P&L total viene de los ``top`` mejores trades."""
    total = sum(t.pnl for t in trades)
    if not trades or total <= 0:
        return float("nan")
    best = sorted((t.pnl for t in trades), reverse=True)[:top]
    return float(sum(best) / total)


def reliability(n_trades: int) -> str:
    """Semáforo: con pocos trades no se puede concluir nada."""
    if n_trades < 30:
        return "insuficiente"
    if n_trades < 100:
        return "débil"
    return "razonable"


def compute_metrics(
    equity: pd.Series,
    trades: Iterable[Trade] = (),
    *,
    exposure: pd.Series | None = None,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> dict[str, float | int | str]:
    """Todas las métricas de una curva de equity y su lista de trades."""
    trades = list(trades)
    equity = equity.astype("float64")
    mdd = max_drawdown(equity)
    cagr_value = cagr(equity)

    metrics: dict[str, float | int | str] = {
        "initial_equity": float(equity.iloc[0]) if len(equity) else 0.0,
        "final_equity": float(equity.iloc[-1]) if len(equity) else 0.0,
        "total_return": (
            float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) > 1 else 0.0
        ),
        "cagr": cagr_value,
        "max_drawdown": mdd,
        "max_drawdown_days": max_drawdown_days(equity),
        "sharpe": sharpe(equity, periods_per_year),
        "sortino": sortino(equity, periods_per_year),
        "calmar": (cagr_value / abs(mdd)) if mdd < 0 else 0.0,
        "profit_factor": profit_factor(trades),
        "win_rate": win_rate(trades),
        "expectancy_r": expectancy_r(trades),
        "win_loss_ratio": win_loss_ratio(trades),
        "n_trades": len(trades),
        "reliability": reliability(len(trades)),
        "max_consecutive_losses": max_consecutive_losses(trades),
        "top5_concentration": top_trades_concentration(trades),
        "avg_bars_held": float(np.mean([t.bars_held for t in trades])) if trades else 0.0,
        "total_commission": float(sum(t.commission for t in trades)),
        "total_slippage": float(sum(t.slippage for t in trades)),
        "exposure_pct": (
            float((exposure > 0).mean()) if exposure is not None and len(exposure) else 0.0
        ),
    }
    return metrics
