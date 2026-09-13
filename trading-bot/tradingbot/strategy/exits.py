"""Capas de salida. Hoy hay tres: hard stop, trailing chandelier y take profit.

Orden de prioridad dentro de una misma vela (criterio conservador: siempre el
peor caso para el trade), tal como está en PLAN.md:

1. Gap de apertura por debajo del stop -> fill en la apertura, no en el stop.
2. Hard stop **y trailing** contra el ``low``. Son el mismo nivel
   (``position.stop_current``): el trailing no es otra orden, es la misma orden
   movida hacia arriba. Lo que cambia es quién la puso ahí, y eso lo dice
   ``position.stop_source``.
3. Take profit contra el ``high``. Si en la misma vela se tocan stop y objetivo,
   **gana el stop**: con velas diarias no se sabe cuál ocurrió primero. Vale
   igual cuando el stop es el del trailing.
4. Salidas evaluadas al cierre (por ahora solo ``exits.signal``) -> fill en la
   apertura siguiente.

**Cuándo se recalcula el nivel del trailing.** Al **cierre** de cada vela, con el
máximo y el ATR ya conocidos de esa vela, y rige desde la vela siguiente. No se
recalcula intrabar: usar el ``high`` de la vela ``t`` para mover el stop y después
comparar contra el ``low`` de esa misma vela ``t`` sería mirar el futuro adentro de
la barra. El precio de eso es que el trailing llega un día tarde, y es el mismo
precio que paga toda la ejecución del motor (señal al cierre de ``t``, orden en la
apertura de ``t+1``).

Las capas que faltan (break-even, reversión, giveback, time stop, régimen,
earnings) son del torneo de la tanda 2C y ``config.py`` las rechaza
explícitamente.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from tradingbot.strategy.position import Position

#: motivos de salida que registra el Trade
REASON_GAP = "gap_stop"
REASON_STOP = "hard_stop"
REASON_TRAILING = "trailing_stop"
REASON_TARGET = "take_profit"
REASON_SIGNAL = "signal"
REASON_EOD = "fin_del_backtest"
REASON_GAP_PREFIX = "gap_"

#: nombre de la capa en ``position.stop_source`` cuando el stop nunca se movió
SOURCE_HARD_STOP = "hard_stop"


class IntrabarExit(NamedTuple):
    reason: str
    price: float


def stop_distance(
    mode: str,
    *,
    price: float,
    atr_value: float,
    multiple: float,
    pct: float | None,
) -> float:
    """Distancia entrada-stop, es decir 1R por acción."""
    if mode == "atr":
        if atr_value is None or not math.isfinite(atr_value):
            return float("nan")
        return float(multiple) * float(atr_value)
    if mode == "pct":
        if pct is None:
            raise ValueError("hard_stop mode 'pct' necesita 'pct'")
        return float(price) * float(pct) / 100.0
    raise ValueError(f"hard_stop mode '{mode}' no soportado en la tanda 1")


def stop_price(entry_price: float, risk_per_share: float, direction: int = 1) -> float:
    return entry_price - direction * risk_per_share


def target_price(
    entry_price: float, risk_per_share: float, ratio: float, direction: int = 1
) -> float:
    return entry_price + direction * ratio * risk_per_share


def chandelier_stop(
    peak_price: float, atr_value: float, multiple: float, direction: int = 1
) -> float:
    """Nivel del trailing chandelier: ``multiple`` × ATR por debajo del máximo.

    El ancla es el **máximo alcanzado desde la entrada**, no el cierre: si el ancla
    fuera el precio de hoy, el nivel bajaría cuando el precio baja y ``raise_stop``
    lo rechazaría, o sea que la capa no haría nada en los retrocesos, que es
    cuando tiene que hacer algo.

    Devuelve ``nan`` si el ATR todavía no vale (warmup): ``raise_stop`` compara y
    ``nan > x`` es ``False``, así que un ATR sin valor deja el stop donde está en
    vez de moverlo a cualquier lado. Igual el motor filtra antes; esto es el
    cinturón además de los tiradores.
    """
    if atr_value is None or not math.isfinite(atr_value):
        return float("nan")
    return float(peak_price) - direction * float(multiple) * float(atr_value)


def stop_reasons(position: Position) -> tuple[str, str]:
    """``(motivo si abre debajo del stop, motivo si el low lo toca)``.

    La salida se atribuye a la capa que puso el stop donde estaba, no a "stop" a
    secas. Con el stop sin mover son los motivos de la tanda 1 —``gap_stop`` y
    ``hard_stop``— y por eso los trades sin trailing siguen leyéndose igual que
    antes; con el stop movido, el motivo lleva el nombre de la capa que lo movió.
    """
    if position.stop_moves == 0:
        return REASON_GAP, REASON_STOP
    source = position.stop_source
    return f"{REASON_GAP_PREFIX}{source}", source


def resolve_intrabar_exit(
    position: Position,
    *,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    opened_this_bar: bool = False,
) -> IntrabarExit | None:
    """Aplica el orden de prioridad intrabar. Devuelve motivo y precio, o None.

    ``opened_this_bar`` evita el absurdo de "salir por gap" en la misma vela en
    la que se entró en la apertura: ahí el gap ya ocurrió antes de la compra.
    """
    stop = position.stop_current
    target = position.target_price
    motivo_gap, motivo_stop = stop_reasons(position)

    if position.direction > 0:
        if not opened_this_bar and bar_open <= stop:
            # la vela abrió debajo del stop: el fill es en la apertura, no en el stop
            return IntrabarExit(motivo_gap, bar_open)
        if bar_low <= stop:
            return IntrabarExit(motivo_stop, stop)
        if target is not None and bar_high >= target:
            return IntrabarExit(REASON_TARGET, target)
        return None

    # corto: contemplado en el contrato, no implementado en esta tanda
    raise NotImplementedError("short selling no está implementado")
