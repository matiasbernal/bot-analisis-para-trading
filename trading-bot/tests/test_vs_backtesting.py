"""Cotejo del motor propio contra `backtesting.py`.

Escribimos el motor para tener control total del modelo de ejecución y de costos
—que es donde estas librerías esconden supuestos—, y el riesgo de eso son bugs
sutiles. La mitigación es esta: la misma estrategia simple en los dos motores,
comparando CAGR, cantidad de trades y max drawdown.

Para que la comparación sea de manzanas con manzanas se apaga todo lo que
`backtesting.py` no hace: sin costos, sin objetivo, con el stop tan lejos que
nunca se toca, y con el tamaño máximo que permita el cash (que es lo que hace
`self.buy()` por defecto).
"""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import make_strategy

from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.metrics import cagr, max_drawdown

backtesting = pytest.importorskip("backtesting", reason="backtesting.py no está instalado")

from backtesting import Backtest, Strategy  # noqa: E402
from backtesting.lib import crossover  # noqa: E402

FAST, SLOW = 10, 30


def _sma(values, period):
    return pd.Series(values).rolling(period).mean()


class SmaCross(Strategy):
    def init(self):
        self.fast = self.I(_sma, self.data.Close, FAST)
        self.slow = self.I(_sma, self.data.Close, SLOW)

    def next(self):
        if crossover(self.fast, self.slow):
            self.buy()
        elif crossover(self.slow, self.fast):
            self.position.close()


def _our_config(symbol: str):
    return make_strategy(
        universe=[symbol],
        warmup_bars=SLOW,
        indicators={
            "sma_fast": {"type": "sma", "period": FAST},
            "sma_slow": {"type": "sma", "period": SLOW},
        },
        entry={"all": [{"left": "sma_fast", "op": "crosses_above", "right": "sma_slow"}]},
        exits={
            "signal": {"any": [{"left": "sma_fast", "op": "crosses_below", "right": "sma_slow"}]},
            # stop tan lejos que nunca se toca, y sin objetivo: solo señal
            "hard_stop": {"mode": "pct", "pct": 99.99},
            "take_profit": None,
        },
        risk={
            "position_sizing": {"risk_pct": 100.0},
            "max_position_pct": 100.0,
            "max_open_positions": 1,
        },
        execution={"commission_pct": 0.0, "slippage_pct": 0.0},
    )


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "SPY", "QQQ"])
def test_cruce_de_medias_da_lo_mismo_en_los_dos_motores(symbol, universe_frames):
    df = universe_frames[symbol]

    ours = run_backtest(_our_config(symbol), {symbol: df})
    theirs = Backtest(
        df.rename(columns=str.title), SmaCross, cash=10_000, commission=0.0, finalize_trades=True
    ).run()
    their_equity = theirs["_equity_curve"]["Equity"]

    assert len(ours.trades) == int(theirs["# Trades"])

    nuestro_cagr, su_cagr = ours.metrics["cagr"], cagr(their_equity)
    # 5% relativo, o media décima de punto de CAGR: con CAGR cerca de cero el
    # porcentaje relativo no significa nada
    assert nuestro_cagr == pytest.approx(su_cagr, rel=0.05) or abs(
        nuestro_cagr - su_cagr
    ) < 0.005

    assert ours.metrics["max_drawdown"] == pytest.approx(max_drawdown(their_equity), rel=0.05)
    assert ours.metrics["final_equity"] == pytest.approx(their_equity.iloc[-1], rel=0.05)
