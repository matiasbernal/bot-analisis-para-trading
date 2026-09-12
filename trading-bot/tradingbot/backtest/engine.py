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
    risk_target: float = 0.0
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
    #: distancia al stop en % del precio de cierre, barra a barra
    stop_pct: np.ndarray
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
    #: buy & hold de SPY: la referencia de mercado que exige la regla de rigor 5
    spy: pd.Series | None = None
    spy_metrics: dict | None = None
    #: de dónde salió la serie de SPY, o por qué no está
    spy_note: str = ""
    #: SPY forma parte del universo, así que está contado dos veces
    spy_in_universe: bool = False
    #: avisos sobre quién decide el tamaño de la posición (ver config.sizing_threshold_pct)
    sizing_warnings: list[str] = field(default_factory=list)
    #: el rango pedido en el YAML, cuando los datos no llegan a cubrirlo
    period_requested: tuple[str, str] | None = None
    data_hash: str = ""
    manifest: dict = field(default_factory=dict)

    @property
    def trades_frame(self) -> pd.DataFrame:
        return self._frame(self.trades)

    @property
    def rule_trades(self) -> list[Trade]:
        """Los trades que cerró una regla del sistema. Son los que se miden."""
        return [t for t in self.trades if not t.is_forced_close]

    @property
    def forced_closes(self) -> list[Trade]:
        """Posiciones que seguían abiertas cuando se acabaron los datos."""
        return [t for t in self.trades if t.is_forced_close]

    @property
    def rule_trades_frame(self) -> pd.DataFrame:
        return self._frame(self.rule_trades)

    @staticmethod
    def _frame(trades: list[Trade]) -> pd.DataFrame:
        portfolio = Portfolio(initial_cash=1.0)
        portfolio.trades = trades
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

    # El warmup se descarta ACÁ, sobre las señales ya calculadas y antes de que
    # el loop las vea: durante esas barras los indicadores existen pero todavía
    # no valen (un RSI sembrado con catorce velas no coincide con ninguna
    # referencia). Se enmascaran las dos señales, no solo la de entrada: hoy no
    # se puede salir de una posición que no se pudo abrir, pero cuando la Fase 3
    # agregue capas que leen indicadores al cierre nadie se va a acordar de esto.
    warmup = min(config.warmup_bars, len(entry))
    entry[:warmup] = False
    exit_signal[:warmup] = False

    hard_stop = config.exits.hard_stop
    if hard_stop.mode == "atr":
        atr = compute_indicator("atr", df, {"period": hard_stop.atr_period}).to_numpy(
            dtype="float64"
        )
    else:
        atr = np.full(len(df), np.nan)

    closes = df["close"].to_numpy(dtype="float64")
    if hard_stop.mode == "atr":
        stop_pct = hard_stop.multiple * atr / closes * 100.0
    else:
        stop_pct = np.full(len(df), float(hard_stop.pct or np.nan))
    stop_pct[:warmup] = np.nan

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
        stop_pct=stop_pct,
        position_of={date: i for i, date in enumerate(df.index)},
    )


def _sizing_warnings(
    config: StrategyConfig, series: dict[str, SymbolSeries]
) -> list[str]:
    """Avisa cuando el tope de concentración, y no risk_pct, va a decidir el tamaño.

    Con stops en ATR la distancia no se conoce hasta tener los datos, así que el
    aviso se da acá y no en la validación del YAML. Es un aviso, no un error.
    """
    avisos = list(config.static_warnings())
    umbral = config.sizing_threshold_pct

    distancias = np.concatenate([s.stop_pct for s in series.values()])
    distancias = distancias[np.isfinite(distancias)]
    if len(distancias) == 0:
        return avisos

    mediana = float(np.median(distancias))
    atados = float(np.mean(distancias < umbral))
    if config.exits.hard_stop.mode == "atr" and atados > 0.5:
        avisos.append(
            f"risk_pct queda decorativo en buena parte de los trades: la distancia típica "
            f"al stop es {mediana:.2f}% del precio y el tope de concentración manda por "
            f"debajo de risk_pct/max_position_pct = {umbral:.2f}% "
            f"({atados * 100:.0f}% de las barras). Subir max_position_pct o ensanchar el "
            f"stop devuelve el control a risk_pct."
        )
    return avisos


def run_backtest(
    config: StrategyConfig,
    frames: dict[str, pd.DataFrame],
    *,
    lookahead: bool = False,
    spy_frame: pd.DataFrame | None = None,
    spy_note: str = "",
) -> BacktestResult:
    """Corre el backtest sobre las series ya validadas de cada símbolo.

    ``spy_frame`` es la serie de SPY para el benchmark de mercado. Si no se
    pasa, el informe lo dice en vez de omitir la columna en silencio; el motivo
    va en ``spy_note``.
    """
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

    sizing_warnings = _sizing_warnings(config, series)

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
    sizing_counts: dict[str, int] = {"riesgo": 0, "tope": 0, "cash": 0}

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
                    risk_target=order.risk_target,
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

            # quién decidió el tamaño: si no fue el riesgo, risk_pct es decorativo
            sizing_counts[
                "tope" if "max_position_pct" in result.reason
                else "cash" if "cash" in result.reason
                else "riesgo"
            ] += 1

            pending[symbol] = PendingOrder(
                symbol=symbol,
                side="buy",
                execute_on=next_date,
                shares=result.shares,
                risk_per_share=result.risk_per_share,
                risk_target=sizing_equity * sizing.risk_pct / 100.0,
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
    bench_start = index[min(config.warmup_bars, len(index) - 1)]
    benchmark = buy_and_hold(
        sliced,
        initial_cash=config.backtest.initial_cash,
        costs=costs,
        index=index,
        start=bench_start,
    )

    spy_series = spy_metrics = None
    if spy_frame is not None and not spy_frame.empty:
        spy_sliced = spy_frame
        if start is not None:
            spy_sliced = spy_sliced[spy_sliced.index >= start]
        if end is not None:
            spy_sliced = spy_sliced[spy_sliced.index <= end]
        if not spy_sliced.empty:
            spy_series = buy_and_hold(
                {"SPY": spy_sliced},
                initial_cash=config.backtest.initial_cash,
                costs=costs,
                index=index,
                start=bench_start,
            ).rename("spy")
            spy_metrics = compute_metrics(spy_series)
        else:
            spy_note = spy_note or "SPY no tiene velas en el rango del backtest"

    # Las estadísticas de trades se calculan sobre los que cerró una regla: el
    # cierre forzado por fin de datos no es una operación del sistema y mete
    # ruido en win rate, expectancy y profit factor. Los costos sí se suman
    # sobre todos, porque esa plata se pagó igual.
    rule_trades = [t for t in portfolio.trades if not t.is_forced_close]
    forced = [t for t in portfolio.trades if t.is_forced_close]
    metrics = compute_metrics(equity, rule_trades, exposure=exposure_series)
    metrics["total_commission"] = float(sum(t.commission for t in portfolio.trades))
    metrics["total_slippage"] = float(sum(t.slippage for t in portfolio.trades))
    metrics["open_at_end"] = len(forced)
    metrics["open_at_end_pnl"] = float(sum(t.pnl for t in forced))
    metrics["sizing_by_risk"] = sizing_counts["riesgo"]
    metrics["sizing_by_cap"] = sizing_counts["tope"]
    metrics["sizing_by_cash"] = sizing_counts["cash"]

    return BacktestResult(
        config=config,
        equity=equity,
        benchmark=benchmark,
        trades=portfolio.trades,
        rejections=portfolio.rejections,
        exposure=exposure_series,
        metrics=metrics,
        benchmark_metrics=compute_metrics(benchmark),
        symbols=sorted(sliced),
        spy=spy_series,
        spy_metrics=spy_metrics,
        spy_note=spy_note,
        spy_in_universe="SPY" in sliced,
        sizing_warnings=sizing_warnings,
        period_requested=(
            str(config.backtest.start) if config.backtest.start else "",
            str(config.backtest.end) if config.backtest.end else "",
        ),
    )
