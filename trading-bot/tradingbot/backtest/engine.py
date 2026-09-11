"""Loop barra a barra. El orden de las operaciones es el contrato del motor.

Para cada fecha ``t`` del índice unificado (PLAN.md, "Contratos entre capas"):

1. **Apertura de t**: se llenan las órdenes pendientes generadas en ``t-1`` a
   ``open[t]`` ± slippage.
2. **Intrabar t**: si la vela abrió debajo del stop, salida por gap en la
   apertura; si no, ``low[t] <= stop`` -> salida al stop; si no,
   ``high[t] >= objetivo`` -> salida al objetivo. Stop antes que objetivo:
   si los dos se tocan en la misma vela, gana el stop.
3. **Cierre de t**: se actualizan excursiones y barras, y se evalúan entradas y
   salidas por regla **con la vela ya cerrada** -> órdenes pendientes para
   ``t+1``. Si hay más entradas que lugares, se ordenan por símbolo
   (determinístico).
4. Se registra la equity a ``close[t]`` (mark-to-market).

De ahí sale la regla de oro: la señal se evalúa al cierre de ``t`` y se ejecuta
en la apertura de ``t+1``. Nunca se usa un dato de ``t+1`` para decidir en ``t``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradingbot.backtest.costs import CostModel
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.portfolio import Portfolio, Rejection, Trade, buy_and_hold
from tradingbot.config import StrategyConfig
from tradingbot.indicators.registry import compute_indicator
from tradingbot.strategy import exits as exit_rules
from tradingbot.strategy.engine import build_context, signals_for
from tradingbot.strategy.risk import size_position


@dataclass
class PendingOrder:
    symbol: str
    side: str  # "buy" | "sell"
    execute_on: pd.Timestamp
    shares: int = 0
    risk_per_share: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class SymbolSeries:
    """Todo lo que el loop necesita de un símbolo, ya vectorizado."""

    symbol: str
    index: pd.DatetimeIndex
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    entry: np.ndarray
    exit_signal: np.ndarray
    atr: np.ndarray
    position_of: dict[pd.Timestamp, int]

    def next_date(self, i: int) -> pd.Timestamp | None:
        return self.index[i + 1] if i + 1 < len(self.index) else None


@dataclass
class BacktestResult:
    config: StrategyConfig
    equity: pd.Series
    benchmark: pd.Series
    trades: list[Trade]
    rejections: list[Rejection]
    exposure: pd.Series
    metrics: dict
    benchmark_metrics: dict
    symbols: list[str]
    data_hash: str = ""
    manifest: dict = field(default_factory=dict)

    @property
    def trades_frame(self) -> pd.DataFrame:
        portfolio = Portfolio(initial_cash=1.0)
        portfolio.trades = self.trades
        return portfolio.trades_frame()


def prepare_symbol(
    config: StrategyConfig, symbol: str, df: pd.DataFrame, *, lookahead: bool = False
) -> SymbolSeries:
    """Calcula indicadores y señales de un símbolo (vectorizado, una sola vez)."""
    ctx = build_context(df, config.indicators)
    signals = signals_for(config.entry, config.exits.signal, ctx)

    entry = signals["entry"].to_numpy(dtype=bool).copy()
    exit_signal = signals["exit_signal"].to_numpy(dtype=bool).copy()

    if lookahead:
        # SOLO para el test de cordura del PLAN.md: un oráculo que mira el cierre
        # de MAÑANA y compra cada día que va a subir. Tiene que dar resultados
        # absurdamente buenos; si el motor honesto diera lo mismo, habría un bug.
        closes = df["close"].to_numpy(dtype="float64")
        manana_sube = np.append(closes[1:] > closes[:-1], False)
        entry = manana_sube
        exit_signal = ~manana_sube

    warmup = min(config.warmup_bars, len(entry))
    entry[:warmup] = False

    hard_stop = config.exits.hard_stop
    if hard_stop.mode == "atr":
        atr = compute_indicator("atr", df, {"period": hard_stop.atr_period}).to_numpy(
            dtype="float64"
        )
    else:
        atr = np.full(len(df), np.nan)

    return SymbolSeries(
        symbol=symbol,
        index=df.index,
        open=df["open"].to_numpy(dtype="float64"),
        high=df["high"].to_numpy(dtype="float64"),
        low=df["low"].to_numpy(dtype="float64"),
        close=df["close"].to_numpy(dtype="float64"),
        entry=entry,
        exit_signal=exit_signal,
        atr=atr,
        position_of={date: i for i, date in enumerate(df.index)},
    )


def run_backtest(
    config: StrategyConfig,
    frames: dict[str, pd.DataFrame],
    *,
    lookahead: bool = False,
) -> BacktestResult:
    """Corre el backtest sobre las series ya validadas de cada símbolo."""
    if not frames:
        raise ValueError("no hay datos para ningún símbolo del universo")

    start = pd.Timestamp(config.backtest.start) if config.backtest.start else None
    end = pd.Timestamp(config.backtest.end) if config.backtest.end else None

    sliced: dict[str, pd.DataFrame] = {}
    for symbol in sorted(frames):
        df = frames[symbol]
        if start is not None:
            df = df[df.index >= start]
        if end is not None:
            df = df[df.index <= end]
        if not df.empty:
            sliced[symbol] = df
    if not sliced:
        raise ValueError("ningún símbolo tiene velas en el rango del backtest")

    series = {
        symbol: prepare_symbol(config, symbol, df, lookahead=lookahead)
        for symbol, df in sliced.items()
    }

    index = pd.DatetimeIndex(sorted(set().union(*(s.index for s in series.values()))))
    costs = CostModel(
        commission_pct=config.execution.commission_pct,
        slippage_pct=config.execution.slippage_pct,
    )
    portfolio = Portfolio(initial_cash=config.backtest.initial_cash, costs=costs)

    sizing = config.risk.position_sizing
    take_profit = config.exits.take_profit
    target_ratio = (
        take_profit.ratio if take_profit is not None and take_profit.enabled else None
    )
    hard_stop = config.exits.hard_stop

    pending: dict[str, PendingOrder] = {}
    last_close: dict[str, float] = {}
    entry_bar: dict[str, int] = {}
    opened_today: set[str] = set()
    exposure: list[int] = []

    for when in index:
        opened_today.clear()

        # --- 1. apertura: se llenan las órdenes pendientes de t-1 -----------
        for symbol in sorted(pending):
            order = pending[symbol]
            if order.execute_on != when:
                continue
            data = series[symbol]
            i = data.position_of[when]
            reference = float(data.open[i])

            if order.side == "sell":
                if symbol in portfolio.positions:
                    portfolio.close_position(
                        symbol,
                        when=when,
                        reference_price=reference,
                        reasons=order.reasons,
                        bars_held=i - entry_bar[symbol],
                    )
            elif symbol not in portfolio.positions:
                position = portfolio.open_position(
                    symbol=symbol,
                    when=when,
                    reference_price=reference,
                    shares=order.shares,
                    risk_per_share=order.risk_per_share,
                    target_ratio=target_ratio,
                )
                if position is not None:
                    entry_bar[symbol] = i
                    opened_today.add(symbol)
            del pending[symbol]

        # --- 2. intrabar: gap, stop, objetivo (en ese orden) ---------------
        for symbol in sorted(portfolio.positions):
            data = series[symbol]
            i = data.position_of.get(when)
            if i is None:
                continue
            position = portfolio.positions[symbol]
            position.update_excursions(float(data.high[i]), float(data.low[i]))
            hit = exit_rules.resolve_intrabar_exit(
                position,
                bar_open=float(data.open[i]),
                bar_high=float(data.high[i]),
                bar_low=float(data.low[i]),
                opened_this_bar=symbol in opened_today,
            )
            if hit is not None:
                portfolio.close_position(
                    symbol,
                    when=when,
                    reference_price=hit.price,
                    reasons=[hit.reason],
                    bars_held=i - entry_bar[symbol],
                )
                pending.pop(symbol, None)

        # --- 3. cierre: se evalúan las reglas con la vela ya cerrada -------
        for symbol in sorted(series):
            data = series[symbol]
            i = data.position_of.get(when)
            if i is None:
                continue
            last_close[symbol] = float(data.close[i])
            if symbol in portfolio.positions:
                portfolio.positions[symbol].bars_held = i - entry_bar[symbol]

        equity_now = portfolio.equity(last_close)
        sizing_equity = (
            equity_now if sizing.on == "current_equity" else config.backtest.initial_cash
        )

        for symbol in sorted(series):  # orden determinístico
            data = series[symbol]
            i = data.position_of.get(when)
            if i is None:
                continue
            next_date = data.next_date(i)

            if symbol in portfolio.positions:
                if data.exit_signal[i] and symbol not in pending and next_date is not None:
                    pending[symbol] = PendingOrder(
                        symbol=symbol,
                        side="sell",
                        execute_on=next_date,
                        reasons=[exit_rules.REASON_SIGNAL],
                    )
                continue

            if not data.entry[i] or symbol in pending or next_date is None:
                continue

            committed = len(portfolio.positions) + sum(
                1 for o in pending.values() if o.side == "buy"
            ) - sum(1 for o in pending.values() if o.side == "sell")
            if committed >= config.risk.max_open_positions:
                portfolio.rejections.append(
                    Rejection(when.date(), symbol, "max_open_positions alcanzado")
                )
                continue

            price = float(data.close[i])
            risk_per_share = exit_rules.stop_distance(
                hard_stop.mode,
                price=price,
                atr_value=float(data.atr[i]),
                multiple=hard_stop.multiple,
                pct=hard_stop.pct,
            )
            result = size_position(
                equity=sizing_equity,
                price=price,
                risk_per_share=risk_per_share,
                risk_pct=sizing.risk_pct,
                max_position_pct=config.risk.max_position_pct,
                cash=portfolio.cash,
            )
            if not result.ok:
                portfolio.rejections.append(Rejection(when.date(), symbol, result.reason))
                continue

            pending[symbol] = PendingOrder(
                symbol=symbol,
                side="buy",
                execute_on=next_date,
                shares=result.shares,
                risk_per_share=result.risk_per_share,
            )

        # --- 4. mark-to-market al cierre de t -------------------------------
        portfolio.mark(when, last_close)
        exposure.append(len(portfolio.positions))

    # cierre forzado de lo que quede abierto, al último cierre disponible
    for symbol in sorted(portfolio.positions):
        data = series[symbol]
        i = len(data.index) - 1
        portfolio.close_position(
            symbol,
            when=data.index[i],
            reference_price=float(data.close[i]),
            reasons=[exit_rules.REASON_EOD],
            bars_held=i - entry_bar[symbol],
        )
    if portfolio.equity_values:
        # la última marca ya no tiene posiciones abiertas: es todo cash realizado
        portfolio.equity_values[-1] = portfolio.equity(last_close)

    equity = portfolio.equity_curve()
    exposure_series = pd.Series(exposure, index=index, name="exposure")
    benchmark = buy_and_hold(
        sliced,
        initial_cash=config.backtest.initial_cash,
        costs=costs,
        index=index,
        start=index[min(config.warmup_bars, len(index) - 1)],
    )

    return BacktestResult(
        config=config,
        equity=equity,
        benchmark=benchmark,
        trades=portfolio.trades,
        rejections=portfolio.rejections,
        exposure=exposure_series,
        metrics=compute_metrics(equity, portfolio.trades, exposure=exposure_series),
        benchmark_metrics=compute_metrics(benchmark),
        symbols=sorted(sliced),
    )
