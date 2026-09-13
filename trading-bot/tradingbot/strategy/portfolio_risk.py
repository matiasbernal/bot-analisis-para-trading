"""Riesgo a nivel cartera: los cinco controles de la tanda 2B.

Un trader con veinte años no piensa en "este trade": piensa en cuánto tiene
expuesto en total y cuándo tiene que dejar de operar. El plan original solo tenía
riesgo por trade, y eso deja pasar el error caro: cinco operaciones
correlacionadas no son cinco apuestas, son una grande.

| Control | Dónde vive | Qué evita |
|---|---|---|
| ``max_position_pct`` | ``strategy/risk.py`` (ya estaba en la tanda 1) | concentración: un trade de 0.5R que ocupa el 60% del capital sigue siendo mala idea |
| ``max_portfolio_heat_r`` | acá, ``heat_en_pesos`` | tener todo el riesgo desplegado a la vez |
| ``max_per_group`` | acá, ``cupo_de_grupo`` | cinco tecnológicas que son una sola posición |
| ``circuit_breaker.monthly_drawdown_pct`` | acá, ``GuardiaDeCartera`` | la racha mala: se deja de abrir hasta el mes que viene |
| ``circuit_breaker.peak_drawdown_pct`` | acá, ``GuardiaDeCartera`` | la invalidación del sistema: se cierra todo y no se reanuda |

**Estos cinco no son candidatos del torneo de la 2C, son restricciones.** No se
miden con el banco A/B ni se les calcula poder: se cumplen o no se cumplen. Por
eso 2B pudo avanzar sin esperar datos reales, mientras 2C sigue parada.

---

**El heat va en PESOS, no contando R nominales.** Es la corrección que la tanda 1
dejó escrita (PLAN.md y README, "La unidad de riesgo"):

    heat = Σ(riesgo real de las posiciones abiertas) / equity

y ``max_portfolio_heat_r: 4.0`` se lee como **4% del equity en riesgo abierto**.
El riesgo real de cada posición es ``acciones × (entrada − stop)``, que es
exactamente ``Position.risk_at_stake(entry_price)``. Contar "cuatro posiciones de
1R" daría 4R nominales que en la práctica son ~3.1R —el tamaño se redondea a
acciones enteras y el tope de concentración recorta—, y el cortacircuito quedaría
calibrado sobre una unidad que no es la que dice.

**Y se suma la parte positiva de cada posición, no la suma con signo.**
``risk_at_stake`` se vuelve **negativo** cuando el stop pasó arriba de la entrada
—que es lo que hace el trailing una vez armado, y lo que va a hacer el break-even
de la 2C—. Ahí esa posición no tiene riesgo a la mesa, tiene ganancia asegurada, y
su aporte al heat es cero. Lo que no puede hacer es aportar riesgo **negativo**:
una posición ya cubierta no cancela el riesgo de otra que sí está expuesta. Sumar
con signo dejaría que dos trades ganadores "paguen" la apertura de un tercero
perdedor, que es al revés de para qué está el control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

import pandas as pd

from tradingbot.strategy.position import Position

#: prefijos de los motivos de rechazo. El informe agrupa por acá, así que son
#: parte del contrato con reporting/report.py y no texto suelto.
MOTIVO_HEAT = "heat de cartera"
MOTIVO_GRUPO = "límite por grupo"
MOTIVO_CB_MES = "cortacircuito mensual"
MOTIVO_CB_PICO = "cortacircuito desde el pico"

#: motivo de salida cuando el cortacircuito del pico cierra todo
RAZON_CIERRE_POR_PICO = "cortacircuito_pico"


class GroupLabelError(ValueError):
    """Falta la etiqueta de un símbolo y el límite por grupo no se puede aplicar."""


def riesgo_de(position: Position) -> float:
    """Riesgo real de una posición abierta, en pesos, nunca negativo.

    ``risk_at_stake`` evaluado **en el precio de entrada**, que es la fórmula que
    fija el PLAN (``acciones × (entrada − stop)``): mide el riesgo del plan del
    trade, no lo que se perdería desde la marca de hoy. Las dos lecturas son
    defendibles y la elegida es esta porque es la que hace que
    ``max_portfolio_heat_r`` signifique lo mismo el día que se abre la posición
    que tres semanas después: si el ancla fuera el cierre de hoy, el heat subiría
    solo porque el precio subió, sin que nadie haya tomado más riesgo.
    """
    return max(position.risk_at_stake(position.entry_price), 0.0)


def heat_en_pesos(positions: Iterable[Position]) -> float:
    return float(sum(riesgo_de(p) for p in positions))


def heat_fraccion(positions: Iterable[Position], equity: float) -> float:
    """El heat como fracción del equity. 0.04 es "4% del equity en riesgo abierto"."""
    if equity <= 0:
        return 0.0
    return heat_en_pesos(positions) / float(equity)


def cupo_de_grupo(
    symbol: str,
    etiqueta: str,
    grupos: Mapping[str, Mapping[str, str]],
) -> str:
    """El grupo de ``symbol`` según ``etiqueta``, o falla diciendo qué falta.

    Un símbolo sin etiqueta no se puede meter en un cajón "otros" en silencio: ese
    cajón sería un grupo con su propio cupo, y el límite pasaría a permitir cosas
    que nadie pidió. Es mejor que el backtest no arranque.
    """
    etiquetas = grupos.get(symbol)
    if not etiquetas or etiqueta not in etiquetas:
        raise GroupLabelError(
            f"max_per_group pide agrupar por '{etiqueta}' y {symbol} no tiene esa "
            f"etiqueta en universe.yaml. Agregala, o sacá '{etiqueta}' de "
            f"risk.max_per_group: un límite por grupo que no sabe a qué grupo "
            f"pertenece un símbolo no es un límite."
        )
    return str(etiquetas[etiqueta])


@dataclass(frozen=True)
class Comprometido:
    """Riesgo ya comprometido por un símbolo: abierto o con la orden mandada.

    Las órdenes pendientes cuentan igual que las posiciones abiertas. Si no
    contaran, cinco señales de la misma noche pasarían las cinco —ninguna ve a las
    otras— y el heat recién se enteraría al día siguiente, con las cinco adentro.
    """

    symbol: str
    riesgo: float


@dataclass
class GuardiaDeCartera:
    """Decide qué señales se pueden tomar y cuándo hay que frenar del todo.

    Es deliberadamente **sin memoria del heat**: cada consulta lo recalcula desde
    las posiciones vivas. Un contador incremental se desincroniza el día que
    varios stops saltan la misma mañana —que es justo el escenario para el que
    existe el control— y el error no se ve, porque el número sigue siendo
    plausible.

    Lo único que sí es estado son los cortacircuitos, porque son latches: el
    mensual se prende y no se apaga hasta que cambia el mes (que el equity se
    recupere dentro del mes no lo levanta: la regla es dejar de operar el mes malo,
    no operar en los repuntes del mes malo), y el del pico no se apaga nunca.
    """

    max_portfolio_heat_r: float | None = None
    max_per_group: Mapping[str, int] = field(default_factory=dict)
    monthly_drawdown_pct: float | None = None
    peak_drawdown_pct: float | None = None
    grupos: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    # --- estado de los cortacircuitos ---
    detenido: bool = False
    mes_bloqueado: bool = False
    _mes: tuple[int, int] | None = None
    _equity_inicio_mes: float = 0.0
    _pico: float = 0.0
    #: por qué está bloqueado ahora mismo, para que el rechazo lo diga con números
    motivo_bloqueo: str = ""

    # --- ciclo de vida del calendario -------------------------------------
    def marcar(self, when: pd.Timestamp, equity: float) -> bool:
        """Se llama al cierre de cada vela. Devuelve si hay que cerrar todo.

        El orden importa: primero se abre el mes nuevo (que levanta el bloqueo
        mensual), después se actualiza el pico, y recién ahí se evalúan los dos
        cortes contra la equity de este cierre. La decisión se toma al cierre y el
        fill es en la apertura siguiente, igual que cualquier otra salida por
        regla del motor: no hay forma de vender al cierre de hoy con una orden que
        se decide al cierre de hoy.
        """
        mes = (when.year, when.month)
        if mes != self._mes:
            self._mes = mes
            self._equity_inicio_mes = float(equity)
            self.mes_bloqueado = False
            if not self.detenido:
                self.motivo_bloqueo = ""
        self._pico = max(self._pico, float(equity))

        if self.detenido:
            return False

        if self.peak_drawdown_pct is not None and self._pico > 0:
            caida = (float(equity) / self._pico - 1.0) * 100.0
            if caida <= -self.peak_drawdown_pct:
                self.detenido = True
                self.motivo_bloqueo = (
                    f"{MOTIVO_CB_PICO}: la equity está {caida:.2f}% abajo del máximo "
                    f"(${self._pico:,.0f}) y el tope es -{self.peak_drawdown_pct:.2f}%. "
                    "Se cierra todo y no se vuelve a abrir."
                )
                return True

        if (
            self.monthly_drawdown_pct is not None
            and not self.mes_bloqueado
            and self._equity_inicio_mes > 0
        ):
            caida = (float(equity) / self._equity_inicio_mes - 1.0) * 100.0
            if caida <= -self.monthly_drawdown_pct:
                self.mes_bloqueado = True
                self.motivo_bloqueo = (
                    f"{MOTIVO_CB_MES}: el mes va {caida:.2f}% y el tope es "
                    f"-{self.monthly_drawdown_pct:.2f}%. No se abre hasta el mes que viene; "
                    "las posiciones abiertas siguen con sus salidas."
                )
        return False

    @property
    def frenado(self) -> bool:
        """No se abre nada: o el sistema está detenido, o el mes está bloqueado."""
        return self.detenido or self.mes_bloqueado

    # --- la decisión por señal --------------------------------------------
    def rechazo_por_freno(self) -> str | None:
        return self.motivo_bloqueo if self.frenado else None

    def rechazo_por_grupo(
        self, symbol: str, comprometidos: Iterable[str]
    ) -> str | None:
        """``None`` si hay lugar; si no, el motivo con la etiqueta y el cupo."""
        if not self.max_per_group:
            return None
        comprometidos = list(comprometidos)
        for etiqueta, tope in self.max_per_group.items():
            grupo = cupo_de_grupo(symbol, etiqueta, self.grupos)
            ocupadas = [
                otro
                for otro in comprometidos
                if otro != symbol and cupo_de_grupo(otro, etiqueta, self.grupos) == grupo
            ]
            if len(ocupadas) >= tope:
                return (
                    f"{MOTIVO_GRUPO} {etiqueta}={grupo}: ya hay {len(ocupadas)} "
                    f"({', '.join(sorted(ocupadas))}) y el tope es {tope}"
                )
        return None

    def rechazo_por_heat(
        self,
        riesgo_nuevo: float,
        comprometidos: Iterable[Comprometido],
        equity: float,
    ) -> str | None:
        """``None`` si el riesgo nuevo entra en el tope; si no, el motivo con los pesos."""
        if self.max_portfolio_heat_r is None or equity <= 0:
            return None
        actual = float(sum(c.riesgo for c in comprometidos))
        total = actual + max(float(riesgo_nuevo), 0.0)
        tope = self.max_portfolio_heat_r / 100.0 * float(equity)
        if total > tope:
            return (
                f"{MOTIVO_HEAT}: {actual / equity * 100:.2f}% abierto "
                f"+ {riesgo_nuevo / equity * 100:.2f}% de esta señal = "
                f"{total / equity * 100:.2f}% del equity, y el tope es "
                f"{self.max_portfolio_heat_r:.2f}% (${tope:,.0f} sobre ${equity:,.0f})"
            )
        return None


def guardia_desde_config(config, grupos: Mapping[str, Mapping[str, str]] | None = None):
    """Arma la guardia a partir de ``config.risk``. Devuelve ``None`` si no hay controles."""
    riesgo = config.risk
    cb = riesgo.circuit_breaker
    if (
        riesgo.max_portfolio_heat_r is None
        and not riesgo.max_per_group
        and cb is None
    ):
        return None
    return GuardiaDeCartera(
        max_portfolio_heat_r=riesgo.max_portfolio_heat_r,
        max_per_group=dict(riesgo.max_per_group or {}),
        monthly_drawdown_pct=cb.monthly_drawdown_pct if cb else None,
        peak_drawdown_pct=cb.peak_drawdown_pct if cb else None,
        grupos=dict(grupos or {}),
    )
