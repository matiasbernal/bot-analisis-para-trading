"""Position sizing y cálculo de 1R.

Es donde más bugs silenciosos aparecen, así que el cálculo está en un solo lugar
y devuelve **por qué** salió lo que salió:

    acciones = floor(equity × risk_pct / (entrada − stop))

luego el tope de concentración ``max_position_pct`` (un stop muy ajustado sin
tope produce posiciones gigantes) y luego el cash disponible. Acciones enteras,
sin fraccionarias. Si el resultado es 0 no hay trade y queda registrado el motivo.

**Cuándo se calcula**: al cierre de la barra de la señal, usando ``close[t]``
como estimación del precio de entrada, porque es lo único que se sabe cuando se
manda una orden market-on-open. En el fill solo se recorta si el cash no alcanza,
nunca se agranda. El stop sí se ancla al precio de fill real, así que la
distancia entrada-stop es exactamente 1R por acción.

**Consecuencia medida** (``scripts/riesgo_realizado.py``): el riesgo inicial
realizado queda entre 0.54R y 0.99R, con media 0.78R sobre la plantilla
ema_cross. Nunca por encima de 1R. El desvío no viene del gap de la apertura
sino del redondeo a acciones enteras y, sobre todo, del tope de concentración.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SizingResult:
    shares: int
    risk_per_share: float
    reason: str

    @property
    def ok(self) -> bool:
        return self.shares > 0


def size_position(
    *,
    equity: float,
    price: float,
    risk_per_share: float,
    risk_pct: float,
    max_position_pct: float,
    cash: float,
) -> SizingResult:
    """Cantidad de acciones a comprar, o 0 con el motivo."""
    if risk_per_share <= 0 or not math.isfinite(risk_per_share):
        return SizingResult(0, risk_per_share, "riesgo por acción no positivo (ATR sin valor)")
    if price <= 0 or not math.isfinite(price):
        return SizingResult(0, risk_per_share, "precio de referencia inválido")
    if equity <= 0:
        return SizingResult(0, risk_per_share, "equity agotado")

    by_risk = math.floor(equity * (risk_pct / 100.0) / risk_per_share)
    if by_risk <= 0:
        return SizingResult(0, risk_per_share, "el riesgo por acción supera el riesgo por trade")

    by_concentration = math.floor(equity * (max_position_pct / 100.0) / price)
    if by_concentration <= 0:
        return SizingResult(0, risk_per_share, "el tope de concentración no alcanza ni 1 acción")

    by_cash = math.floor(cash / price)
    if by_cash <= 0:
        return SizingResult(0, risk_per_share, "no hay cash para comprar ni 1 acción")

    shares = min(by_risk, by_concentration, by_cash)
    if shares == by_concentration < by_risk:
        reason = "limitado por max_position_pct"
    elif shares == by_cash < by_risk:
        reason = "limitado por cash disponible"
    else:
        reason = "ok"
    return SizingResult(int(shares), risk_per_share, reason)
