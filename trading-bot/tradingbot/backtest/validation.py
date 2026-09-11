"""Split in-sample / out-of-sample.

Se afinan parámetros solo sobre el período in-sample. El tramo final se toca una
vez, al final: si se mira veinte veces, deja de ser out-of-sample. Acá el split
solo se **reporta**; la optimización es de la Fase 6.
"""

from __future__ import annotations

import pandas as pd

from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.portfolio import Trade


def split_equity(equity: pd.Series, cut: pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    return equity[equity.index <= cut], equity[equity.index > cut]


def split_trades(trades: list[Trade], cut: pd.Timestamp) -> tuple[list[Trade], list[Trade]]:
    in_sample = [t for t in trades if pd.Timestamp(t.exit_date) <= cut]
    out_sample = [t for t in trades if pd.Timestamp(t.exit_date) > cut]
    return in_sample, out_sample


def in_out_metrics(
    equity: pd.Series, trades: list[Trade], in_sample_end
) -> dict[str, dict] | None:
    """Métricas del tramo in-sample y del out-of-sample, o None si no hay corte."""
    if in_sample_end is None or equity.empty:
        return None
    cut = pd.Timestamp(in_sample_end)
    eq_in, eq_out = split_equity(equity, cut)
    tr_in, tr_out = split_trades(trades, cut)
    if len(eq_in) < 2 or len(eq_out) < 2:
        return None
    return {
        "in_sample": compute_metrics(eq_in, tr_in),
        "out_of_sample": compute_metrics(eq_out, tr_out),
        "cut": cut.strftime("%Y-%m-%d"),
    }
