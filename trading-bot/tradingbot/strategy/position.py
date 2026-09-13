"""Estado de una posición abierta.

Contrato (PLAN.md): ``symbol, entry_date, entry_price, shares, risk_per_share,
stop_current, peak_price, bars_held, partial_taken``. Es lo que en la Fase 4
persiste ``journal.py`` y lo que lee el `scan`.

El motor es consciente de la dirección desde el día 1: ``direction`` vale +1 en
largo y -1 en corto, y R se calcula con signo. El corto no se implementa en esta
tanda, pero agregarlo tiene que ser un flag y no una reescritura.

**Por qué esto es el piso de la tanda 2A y no una capa más.** Cuatro de las siete
capas de salida no se pueden calcular sin memoria de la posición: el break-even y
el trailing necesitan mover el stop sin bajarlo nunca, el giveback necesita el
pico de ganancia no realizada, y el time stop necesita las velas adentro y el
progreso en R. Las cuatro leen el mismo estado, así que el estado va una vez, acá,
con sus invariantes probadas, y no replicado en cada capa.

Las tres invariantes, que son las que los tests fijan:

1. **El stop nunca baja.** Se mueve solo por ``raise_stop``, que devuelve si
   efectivamente se movió y anota **qué capa** lo movió (``stop_source``). No hay
   asignación directa a ``stop_current`` desde afuera.
2. **La unidad de riesgo se fija en la entrada y no se toca.** ``risk_per_share``
   es 1R para siempre, aunque el stop se mueva: si el denominador cambiara a
   mitad del trade, los R de dos trades dejarían de ser comparables y la
   expectancy sumaría peras con manzanas. Lo que cambia al mover el stop es el
   riesgo **a la mesa** (``risk_at_stake``), que es otra cosa y tiene su nombre.
3. **El armado es de una sola vía.** Una capa que se activa en +1R queda activada
   aunque el precio vuelva: si el umbral se volviera a cerrar al retroceder, el
   trailing se desengancharía justo cuando hace falta, que es durante el
   retroceso.
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
    #: 1R declarado por el YAML al momento de la señal (equity x risk_pct), en pesos.
    #: El realizado es shares x risk_per_share y casi nunca coincide: ver README.
    risk_target: float = 0.0
    stop_initial: float = 0.0
    target_price: float | None = None
    trough_price: float = 0.0
    commission_paid: float = 0.0
    slippage_paid: float = 0.0

    #: capas ya activadas (break_even, trailing_stop...). El armado no se revierte.
    armed: set[str] = field(default_factory=set)
    #: cuántas veces se movió el stop. 0 quiere decir que sigue en el stop inicial.
    stop_moves: int = 0
    #: qué capa fijó el stop vigente. Con ``stop_moves == 0`` es el hard stop.
    #: Es lo que la atribución usa para no llamar "hard_stop" a una salida por
    #: trailing: sin esto, las dos capas se ven iguales en el informe y la
    #: pregunta "¿qué regla me saca?" queda sin respuesta.
    stop_source: str = "hard_stop"

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
    def peak_r(self) -> float:
        """R del pico alcanzado desde la entrada. Es el gatillo de las capas.

        Mismo número que ``mfe_r``, con dos nombres a propósito y una sola
        implementación: ``mfe_r`` es cómo se llama cuando se reporta el trade ya
        cerrado, ``peak_r`` es cómo se llama cuando una capa lo lee en vivo para
        decidir si se activa. Si alguna vez hay que distinguirlos (un pico que
        ignore la vela de entrada, por ejemplo), se separan acá y no en siete
        lugares.
        """
        return self.r_multiple(self.peak_price if self.direction > 0 else self.trough_price)

    @property
    def mfe_r(self) -> float:
        return self.peak_r

    @property
    def mae_r(self) -> float:
        return self.r_multiple(self.trough_price if self.direction > 0 else self.peak_price)

    @property
    def stop_r(self) -> float:
        """Dónde está el stop, medido en R desde la entrada.

        Vale −1.0 en la entrada por construcción, 0.0 en break-even exacto, y
        positivo cuando el trailing ya aseguró ganancia. Es la forma de leer de un
        vistazo cuánto riesgo se sacó de la mesa.
        """
        return self.r_multiple(self.stop_current)

    def risk_at_stake(self, price: float) -> float:
        """Riesgo vivo en pesos: lo que se pierde desde ``price`` si salta el stop.

        **No es 1R.** 1R es ``shares × risk_per_share`` y se fija en la entrada;
        esto se mueve con el precio y con el stop. Arranca igual a 1R (precio de
        entrada, stop inicial) y se vuelve **negativo** cuando el stop pasó arriba
        de la entrada, que es exactamente lo que hace el break-even: ahí ya no hay
        riesgo a la mesa sino ganancia asegurada.

        El heat de cartera de la tanda 2B suma la parte positiva de esto, no los R
        nominales: un sistema con cuatro posiciones cuyos stops están todos arriba
        de la entrada no tiene 4R de riesgo, tiene cero.
        """
        return self.direction * (price - self.stop_current) * self.shares

    def giveback_fraction(self, price: float) -> float:
        """Qué fracción de la ganancia máxima no realizada se devolvió.

        Medida en R y no en % del precio: devolver el 40% de una ganancia de 3R es
        1.2R, y "40% del precio del pico" sería otro número, mucho más grande, que
        no es lo que el plan pide.

        Devuelve ``nan`` mientras el pico no sea positivo — si el trade nunca
        estuvo en ganancia no hay nada que devolver, y un 0.0 ahí haría creer que
        la capa está midiendo algo.
        """
        peak = self.peak_r
        if peak <= 0:
            return float("nan")
        return (peak - self.r_multiple(price)) / peak

    # --- movimiento del stop ---------------------------------------------
    def raise_stop(self, new_stop: float, *, source: str = "trailing_stop") -> bool:
        """Mueve el stop **solo a favor**. Devuelve si se movió.

        Es el único camino para tocar ``stop_current``: el trailing y el
        break-even proponen un nivel y acá se decide. Un trailing que baja el stop
        deja de ser un trailing y se convierte en un stop que se agranda cuando el
        trade va mal, que es el error más caro posible.

        ``source`` queda registrado en ``stop_source`` **solo si el stop se movió**:
        una capa que propone un nivel peor que el vigente no se lleva el crédito de
        la salida. Cuando la 2C agregue el break-even, la última capa que ganó la
        puja es la que va a figurar en la atribución, que es lo correcto: es la que
        puso el stop donde estaba cuando saltó.
        """
        mejor = new_stop > self.stop_current if self.direction > 0 else new_stop < self.stop_current
        if not mejor:
            return False
        self.stop_current = float(new_stop)
        self.stop_moves += 1
        self.stop_source = source
        return True

    # --- armado de capas --------------------------------------------------
    def is_armed(self, layer: str) -> bool:
        return layer in self.armed

    def arm_when(self, layer: str, trigger_r: float | None) -> bool:
        """Activa ``layer`` cuando el pico llegó a ``trigger_r``, y no la desactiva.

        ``trigger_r`` en ``None`` o ``<= 0`` significa sin umbral: la capa está
        activa desde la entrada. Se llama una vez por vela y es idempotente.
        """
        if layer in self.armed:
            return True
        if trigger_r is None or trigger_r <= 0 or self.peak_r >= trigger_r:
            self.armed.add(layer)
            return True
        return False

    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.shares
