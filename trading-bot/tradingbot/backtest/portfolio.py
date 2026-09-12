"""Cash, posiciones abiertas, trades cerrados y curva de equity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from tradingbot.backtest.costs import CostModel
from tradingbot.strategy.exits import REASON_EOD
from tradingbot.strategy.position import Position


@dataclass
class Trade:
    """Un trade cerrado. Es lo que va a la tabla del informe y al journal."""

    symbol: str
    entry_date: date
    entry_price: float
    shares: int
    risk_per_share: float
    stop_initial: float
    exit_date: date
    exit_price: float
    exit_reasons: list[str]
    pnl: float
    pnl_r: float
    bars_held: int
    mae_r: float
    mfe_r: float
    commission: float
    slippage: float
    #: 1R declarado al momento de la señal, en pesos (0 si no se registró)
    risk_target: float = 0.0

    @property
    def risk_amount(self) -> float:
        """1R de este trade, en pesos: lo que se perdía si saltaba el stop inicial.

        Es la unidad de riesgo **realizada**, no la declarada en el YAML. Las dos
        difieren porque el tamaño se redondea a acciones enteras y porque el tope
        de concentración recorta posiciones (ver README, "La unidad de riesgo").
        Todo lo que se denomine en R —el heat de cartera de la Fase 3, el riesgo
        de la alerta, las rachas— tiene que usar este número y no el nominal.
        """
        return self.shares * self.risk_per_share

    @property
    def is_forced_close(self) -> bool:
        """Se cerró porque se acabaron los datos, no porque una regla lo dijera.

        No es una operación del sistema: no la decidió ninguna regla y es el
        único fill del motor que ejecuta al cierre en vez de en la apertura
        siguiente. Queda fuera de las estadísticas de trades y se reporta aparte.
        """
        return REASON_EOD in self.exit_reasons

    def as_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_date": pd.Timestamp(self.entry_date),
            "entry_price": self.entry_price,
            "shares": self.shares,
            "stop_initial": self.stop_initial,
            "risk_amount": self.risk_amount,
            "risk_target": self.risk_target,
            "exit_date": pd.Timestamp(self.exit_date),
            "exit_price": self.exit_price,
            "exit_reasons": ",".join(self.exit_reasons),
            "pnl": self.pnl,
            "pnl_r": self.pnl_r,
            "bars_held": self.bars_held,
            "mae_r": self.mae_r,
            "mfe_r": self.mfe_r,
            "commission": self.commission,
            "slippage": self.slippage,
        }


@dataclass
class Rejection:
    """Una señal que no se pudo tomar, con el motivo. Sin esto el backtest miente."""

    date: date
    symbol: str
    reason: str


@dataclass
class Portfolio:
    initial_cash: float
    costs: CostModel = field(default_factory=CostModel)

    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    equity_dates: list[pd.Timestamp] = field(default_factory=list)
    equity_values: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.cash == 0.0:
            self.cash = float(self.initial_cash)

    # -- operaciones -------------------------------------------------------
    def open_position(
        self,
        *,
        symbol: str,
        when: pd.Timestamp,
        reference_price: float,
        shares: int,
        risk_per_share: float,
        target_ratio: float | None,
        risk_target: float = 0.0,
    ) -> Position | None:
        """Compra en ``reference_price`` ± slippage, paga comisión y abre la posición."""
        fill = self.costs.buy_fill(reference_price)
        shares = self.affordable_shares(fill, shares)
        if shares <= 0:
            self.rejections.append(
                Rejection(when.date(), symbol, "sin cash al momento del fill")
            )
            return None

        commission = self.costs.commission(fill, shares)
        self.cash -= fill * shares + commission

        position = Position(
            symbol=symbol,
            entry_date=when.date(),
            entry_price=fill,
            shares=shares,
            risk_per_share=risk_per_share,
            stop_current=fill - risk_per_share,
            peak_price=fill,
            trough_price=fill,
            stop_initial=fill - risk_per_share,
            target_price=(
                fill + target_ratio * risk_per_share if target_ratio is not None else None
            ),
            risk_target=risk_target,
            commission_paid=commission,
            slippage_paid=self.costs.slippage_cost(reference_price, fill, shares),
        )
        self.positions[symbol] = position
        return position

    def affordable_shares(self, fill_price: float, shares: int) -> int:
        """Recorta la cantidad si el cash no alcanza (comisión incluida)."""
        unit_cost = fill_price * (1.0 + self.costs.commission_pct / 100.0)
        if unit_cost <= 0:
            return 0
        return int(min(shares, self.cash // unit_cost))

    def close_position(
        self,
        symbol: str,
        *,
        when: pd.Timestamp,
        reference_price: float,
        reasons: list[str],
        bars_held: int,
    ) -> Trade:
        """Vende en ``reference_price`` ∓ slippage, paga comisión y registra el Trade."""
        position = self.positions.pop(symbol)
        fill = self.costs.sell_fill(reference_price)
        commission = self.costs.commission(fill, position.shares)
        slippage = self.costs.slippage_cost(reference_price, fill, position.shares)
        self.cash += fill * position.shares - commission

        total_commission = position.commission_paid + commission
        total_slippage = position.slippage_paid + slippage
        gross = (fill - position.entry_price) * position.shares * position.direction
        pnl = gross - total_commission
        risk_total = position.risk_per_share * position.shares
        pnl_r = pnl / risk_total if risk_total > 0 else 0.0

        trade = Trade(
            symbol=symbol,
            entry_date=position.entry_date,
            entry_price=position.entry_price,
            shares=position.shares,
            risk_per_share=position.risk_per_share,
            stop_initial=position.stop_initial,
            exit_date=when.date(),
            exit_price=fill,
            exit_reasons=list(reasons),
            pnl=pnl,
            pnl_r=pnl_r,
            bars_held=bars_held,
            mae_r=position.mae_r,
            mfe_r=position.mfe_r,
            commission=total_commission,
            slippage=total_slippage,
            risk_target=position.risk_target,
        )
        self.trades.append(trade)
        return trade

    # -- valuación ---------------------------------------------------------
    def equity(self, last_close: dict[str, float]) -> float:
        value = self.cash
        for symbol, position in self.positions.items():
            value += position.shares * last_close.get(symbol, position.entry_price)
        return value

    def mark(self, when: pd.Timestamp, last_close: dict[str, float]) -> float:
        value = self.equity(last_close)
        self.equity_dates.append(when)
        self.equity_values.append(value)
        return value

    def equity_curve(self) -> pd.Series:
        return pd.Series(
            self.equity_values,
            index=pd.DatetimeIndex(self.equity_dates, name="date"),
            name="equity",
            dtype="float64",
        )

    def trades_frame(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(
                columns=[
                    "symbol", "entry_date", "entry_price", "shares", "stop_initial",
                    "risk_amount", "risk_target", "exit_date", "exit_price", "exit_reasons", "pnl",
                    "pnl_r", "bars_held", "mae_r", "mfe_r", "commission", "slippage",
                ]
            )
        return pd.DataFrame([t.as_row() for t in self.trades])


def buy_and_hold(
    frames: dict[str, pd.DataFrame],
    *,
    initial_cash: float,
    costs: CostModel,
    index: pd.DatetimeIndex,
    start: pd.Timestamp | None = None,
) -> pd.Series:
    """Benchmark: comprar y esperar, equiponderado sobre el universo.

    Paga los mismos costos de entrada que la estrategia (una vez) para que la
    comparación sea justa, y se valúa sobre el mismo índice de fechas.
    """
    symbols = sorted(s for s in frames if not frames[s].empty)
    if not symbols:
        return pd.Series(initial_cash, index=index, name="benchmark", dtype="float64")

    budget = initial_cash / len(symbols)
    cash = float(initial_cash)
    holdings: dict[str, int] = {}
    entry_done: dict[str, bool] = {s: False for s in symbols}

    values: list[float] = []
    last_close: dict[str, float] = {}
    for when in index:
        for symbol in symbols:
            frame = frames[symbol]
            if when not in frame.index:
                continue
            bar = frame.loc[when]
            if not entry_done[symbol] and (start is None or when >= start):
                fill = costs.buy_fill(float(bar["open"]))
                unit = fill * (1.0 + costs.commission_pct / 100.0)
                shares = int(budget // unit) if unit > 0 else 0
                if shares > 0:
                    cash -= fill * shares + costs.commission(fill, shares)
                    holdings[symbol] = shares
                entry_done[symbol] = True
            last_close[symbol] = float(bar["close"])
        value = cash + sum(shares * last_close.get(s, 0.0) for s, shares in holdings.items())
        values.append(value)

    return pd.Series(values, index=index, name="benchmark", dtype="float64")
