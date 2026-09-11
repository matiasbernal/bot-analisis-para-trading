"""Estado de una posición abierta.

Contrato (PLAN.md): ``symbol, entry_date, entry_price, shares, risk_per_share,
stop_current, peak_price, bars_held, partial_taken``. Es lo que en la Fase 4
persiste ``journal.py`` y lo que lee el `scan`.

El motor es consciente de la dirección desde el día 1: ``direction`` vale +1 en
largo y -1 en corto, y R se calcula con signo. El corto no se implementa en esta
tanda, pero agregarlo tiene que ser un flag y no una reescritura.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Position:
    symbol: str
    entry_date: date
    entry_price: float
    shares: int
    risk_per_share: float
    stop_current: float
    peak_price: float
    bars_held: int = 0
    partial_taken: bool = False

    # --- contabilidad interna del backtest ---
    direction: int = 1
    stop_initial: float = 0.0
    target_price: float | None = None
    trough_price: float = 0.0
    commission_paid: float = 0.0
    slippage_paid: float = 0.0

    exit_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.stop_initial == 0.0:
            self.stop_initial = self.stop_current
        if self.trough_price == 0.0:
            self.trough_price = self.entry_price

    # --- excursiones ------------------------------------------------------
    def update_excursions(self, high: float, low: float) -> None:
        """Actualiza pico y valle para MFE/MAE. Se llama una vez por vela."""
        self.peak_price = max(self.peak_price, high)
        self.trough_price = min(self.trough_price, low)

    def r_multiple(self, price: float) -> float:
        """Cuántas R vale la posición a ``price``."""
        if self.risk_per_share <= 0:
            return 0.0
        return self.direction * (price - self.entry_price) / self.risk_per_share

    @property
    def mfe_r(self) -> float:
        return self.r_multiple(self.peak_price if self.direction > 0 else self.trough_price)

    @property
    def mae_r(self) -> float:
        return self.r_multiple(self.trough_price if self.direction > 0 else self.peak_price)

    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.shares
