"""Capas de salida. En la tanda 1 hay dos: hard stop y take profit.

Orden de prioridad dentro de una misma vela (criterio conservador: siempre el
peor caso para el trade), tal como está en PLAN.md:

1. Gap de apertura por debajo del stop -> fill en la apertura, no en el stop.
2. Hard stop contra el ``low``.
3. Take profit contra el ``high``. Si en la misma vela se tocan stop y objetivo,
   **gana el stop**: con velas diarias no se sabe cuál ocurrió primero.
4. Salidas evaluadas al cierre (por ahora solo ``exits.signal``) -> fill en la
   apertura siguiente.

Las capas 2 a 7 del plan (break-even, trailing, reversión, giveback, time stop,
régimen, earnings) son de la tanda 2 y ``config.py`` las rechaza explícitamente.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from tradingbot.strategy.position import Position

#: motivos de salida que registra el Trade
REASON_GAP = "gap_stop"
REASON_STOP = "hard_stop"
REASON_TARGET = "take_profit"
REASON_SIGNAL = "signal"
REASON_EOD = "fin_del_backtest"


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

    if position.direction > 0:
        if not opened_this_bar and bar_open <= stop:
            # la vela abrió debajo del stop: el fill es en la apertura, no en el stop
            return IntrabarExit(REASON_GAP, bar_open)
        if bar_low <= stop:
            return IntrabarExit(REASON_STOP, stop)
        if target is not None and bar_high >= target:
            return IntrabarExit(REASON_TARGET, target)
        return None

    # corto: contemplado en el contrato, no implementado en esta tanda
    raise NotImplementedError("short selling no está implementado")
