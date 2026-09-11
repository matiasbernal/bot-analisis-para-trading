"""Comisión y slippage. Se aplican en **cada** entrada y en **cada** salida.

Ambos se expresan en porcentaje del nocional. El slippage mueve el precio de
ejecución en contra (se compra más caro, se vende más barato) y la comisión se
cobra sobre el nocional ya ejecutado.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    commission_pct: float = 0.0
    slippage_pct: float = 0.0

    def buy_fill(self, reference_price: float) -> float:
        """Precio al que se termina comprando."""
        return reference_price * (1.0 + self.slippage_pct / 100.0)

    def sell_fill(self, reference_price: float) -> float:
        """Precio al que se termina vendiendo."""
        return reference_price * (1.0 - self.slippage_pct / 100.0)

    def commission(self, fill_price: float, shares: int) -> float:
        return abs(fill_price * shares) * self.commission_pct / 100.0

    def slippage_cost(self, reference_price: float, fill_price: float, shares: int) -> float:
        """Cuánto costó el slippage en plata (siempre >= 0)."""
        return abs(fill_price - reference_price) * shares

    @property
    def free(self) -> bool:
        return self.commission_pct == 0.0 and self.slippage_pct == 0.0
