"""Banco de comparación A/B entre dos corridas del motor.

Es el instrumento del torneo de capas (PLAN.md, "El torneo de capas"): la regla
"cada capa se prende sola y se queda solo si mejora la expectancy" no se puede
ejecutar comparando dos números sueltos. Dos corridas de la misma estrategia
sobre los mismos datos dan expectancy 0.42R y 0.51R y eso no dice nada: falta
saber si 0.09R es el efecto de la capa o el ruido de treinta y pico de trades.

Tres decisiones de diseño, con su motivo:

**1. Los trades se emparejan por ``(símbolo, fecha de entrada)``.** Una capa de
salida no cambia las reglas de entrada, así que el mismo trade existe en las dos
corridas y se puede comparar consigo mismo. El emparejamiento igual es *parcial*
y eso no se esconde: salir antes libera capital y lugares, así que la variante
puede tomar entradas que la base rechazó por ``max_open_positions`` o por cash.
Esos trades se reportan aparte (``solo_base`` / ``solo_variante``) en vez de
descartarse en silencio, porque son un efecto real de la capa y no un defecto del
pareo.

**2. El bootstrap es pareado.** Con 31 trades, un test de dos muestras no
distingue nada: casi toda la varianza viene de *qué trades ocurrieron*, no del
efecto de la capa. Al restar trade contra trade esa varianza se cancela y queda
solo lo que la capa cambió. Es la diferencia entre medir con un instrumento y
mirar dos números.

**3. El delta por par se mide en ``pnl_r``, no en pesos.** ``pnl_r`` ya está
normalizado por el riesgo del propio trade, así que no lo ensucia que la variante
compre una cantidad distinta de acciones por tener otra curva de equity. El
efecto en plata sí se reporta, pero al nivel agregado (CAGR, equity final), que es
donde esa realimentación de tamaño corresponde que aparezca.

El p-valor sale de centrar los deltas en cero (la hipótesis nula "la capa no
cambia nada") y contar cuántas réplicas dan una media tan extrema como la
observada. No es el intervalo de percentiles al revés: el intervalo dice cuánto
vale el efecto, el p-valor dice si se distingue de cero, y se calculan distinto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from tradingbot.backtest.engine import BacktestResult
from tradingbot.backtest.metrics import expectancy_r, return_on_risk
from tradingbot.backtest.portfolio import Trade

#: réplicas del bootstrap. 10.000 deja el percentil estable en la tercera decimal.
REPLICAS = 10_000

#: semilla por defecto. El banco tiene que dar lo mismo dos veces o no sirve para decidir.
SEED = 20260912


@dataclass(frozen=True)
class Bootstrap:
    """Una estimación con su incertidumbre. Nunca un número solo."""

    media: float
    lo: float
    hi: float
    p_valor: float
    n: int
    replicas: int = REPLICAS

    @property
    def significativo(self) -> bool:
        """El intervalo no contiene el cero."""
        return self.n > 0 and (self.lo > 0 or self.hi < 0)

    def __str__(self) -> str:
        if self.n == 0:
            return "sin datos"
        return (
            f"{self.media:+.3f} [{self.lo:+.3f}, {self.hi:+.3f}] "
            f"p={self.p_valor:.3f} n={self.n}"
        )


def bootstrap_pareado(
    deltas: Sequence[float],
    *,
    replicas: int = REPLICAS,
    seed: int = SEED,
    alpha: float = 0.05,
) -> Bootstrap:
    """Media de los deltas con intervalo de percentiles y p-valor de dos colas.

    Si todos los deltas son exactamente cero —la variante no cambió nada— el
    resultado es 0 con intervalo [0, 0] y p=1. Es el caso que hay que reconocer
    sin ruido numérico, porque es la prueba de que el banco no inventa efectos.
    """
    valores = np.asarray(list(deltas), dtype="float64")
    n = len(valores)
    if n == 0:
        return Bootstrap(0.0, 0.0, 0.0, 1.0, 0, replicas)

    media = float(valores.mean())
    if np.allclose(valores, 0.0):
        return Bootstrap(0.0, 0.0, 0.0, 1.0, n, replicas)

    rng = np.random.default_rng(seed)
    indices = rng.integers(0, n, size=(replicas, n))
    medias = valores[indices].mean(axis=1)

    lo, hi = np.percentile(medias, [100 * alpha / 2, 100 * (1 - alpha / 2)])

    # p-valor: se centran los deltas en cero (H0 = "la capa no cambia nada") y se
    # cuenta cuántas réplicas de ese mundo dan una media tan lejos del cero como
    # la observada. El +1 en numerador y denominador evita el p=0 imposible.
    centrados = valores - media
    medias_h0 = centrados[rng.integers(0, n, size=(replicas, n))].mean(axis=1)
    extremas = int(np.sum(np.abs(medias_h0) >= abs(media)))
    p_valor = (extremas + 1) / (replicas + 1)

    return Bootstrap(media, float(lo), float(hi), float(p_valor), n, replicas)


def bootstrap_no_pareado(
    base: Sequence[float],
    variante: Sequence[float],
    *,
    replicas: int = REPLICAS,
    seed: int = SEED,
    alpha: float = 0.05,
) -> Bootstrap:
    """Diferencia de medias entre dos muestras independientes.

    Es la versión sin pareo, mucho menos potente, y está acá para mostrar
    **cuánto** se pierde: es el número que daría comparar las dos corridas de
    frente, que es lo que uno haría sin este módulo.
    """
    a = np.asarray(list(base), dtype="float64")
    b = np.asarray(list(variante), dtype="float64")
    if len(a) == 0 or len(b) == 0:
        return Bootstrap(0.0, 0.0, 0.0, 1.0, 0, replicas)

    media = float(b.mean() - a.mean())
    rng = np.random.default_rng(seed)
    ma = a[rng.integers(0, len(a), size=(replicas, len(a)))].mean(axis=1)
    mb = b[rng.integers(0, len(b), size=(replicas, len(b)))].mean(axis=1)
    diffs = mb - ma
    lo, hi = np.percentile(diffs, [100 * alpha / 2, 100 * (1 - alpha / 2)])

    centradas = diffs - media
    extremas = int(np.sum(np.abs(centradas) >= abs(media)))
    p_valor = (extremas + 1) / (replicas + 1)
    return Bootstrap(media, float(lo), float(hi), float(p_valor), min(len(a), len(b)), replicas)


# --- emparejamiento -------------------------------------------------------
def _clave(trade: Trade) -> tuple[str, object]:
    return (trade.symbol, trade.entry_date)


def _mismo_cierre(a: Trade, b: Trade) -> bool:
    return (
        a.exit_date == b.exit_date
        and math.isclose(a.exit_price, b.exit_price, rel_tol=1e-12, abs_tol=1e-9)
        and a.exit_reasons == b.exit_reasons
    )


@dataclass
class Pareo:
    """Resultado de emparejar los trades de dos corridas."""

    pares: list[tuple[Trade, Trade]] = field(default_factory=list)
    solo_base: list[Trade] = field(default_factory=list)
    solo_variante: list[Trade] = field(default_factory=list)

    @property
    def afectados(self) -> list[tuple[Trade, Trade]]:
        """Pares donde la capa efectivamente cambió la salida."""
        return [(a, b) for a, b in self.pares if not _mismo_cierre(a, b)]

    @property
    def fraccion_afectada(self) -> float:
        """La *f* del cálculo de poder: qué fracción de los trades toca la capa."""
        total = len(self.pares) + len(self.solo_base) + len(self.solo_variante)
        if total == 0:
            return 0.0
        tocados = len(self.afectados) + len(self.solo_base) + len(self.solo_variante)
        return tocados / total

    @property
    def deltas_r(self) -> list[float]:
        return [b.pnl_r - a.pnl_r for a, b in self.pares]


def emparejar(base: Sequence[Trade], variante: Sequence[Trade]) -> Pareo:
    """Empareja por (símbolo, fecha de entrada). La clave es única por corrida.

    No puede haber dos trades del mismo símbolo abiertos el mismo día: el motor
    tiene una posición por símbolo. Si alguna vez la hubiera, esto lo tiene que
    detectar y no elegir uno en silencio.
    """
    por_clave_base = {}
    for trade in base:
        clave = _clave(trade)
        if clave in por_clave_base:
            raise ValueError(f"trade repetido en la corrida base: {clave}")
        por_clave_base[clave] = trade

    pareo = Pareo()
    vistas: set[tuple[str, object]] = set()
    for trade in variante:
        clave = _clave(trade)
        if clave in vistas:
            raise ValueError(f"trade repetido en la corrida variante: {clave}")
        vistas.add(clave)
        contraparte = por_clave_base.get(clave)
        if contraparte is None:
            pareo.solo_variante.append(trade)
        else:
            pareo.pares.append((contraparte, trade))
    pareo.solo_base = [t for clave, t in por_clave_base.items() if clave not in vistas]
    return pareo


# --- comparación completa -------------------------------------------------
@dataclass
class Comparacion:
    """Lo que devuelve el banco. Se lee de arriba a abajo y decide."""

    etiqueta_base: str
    etiqueta_variante: str
    pareo: Pareo
    delta_pareado: Bootstrap
    delta_no_pareado: Bootstrap
    expectancy_base: float
    expectancy_variante: float
    ror_base: float
    ror_variante: float
    n_base: int
    n_variante: int
    cagr_base: float
    cagr_variante: float
    mdd_base: float
    mdd_variante: float

    @property
    def fraccion_afectada(self) -> float:
        return self.pareo.fraccion_afectada

    @property
    def menos_trades(self) -> bool:
        return self.n_variante < self.n_base

    @property
    def ror_empeora(self) -> bool:
        return self.ror_variante < self.ror_base

    def veredicto(self) -> str:
        """Aplica las dos reglas de desempate del PLAN, sin interpretación libre.

        1. El default es apagada: empate estadístico = la capa no entra.
        2. Una mejora con menos trades no es mejora hasta mirar ``return_on_risk``.
        """
        if not self.pareo.afectados and not self.pareo.solo_base and not self.pareo.solo_variante:
            return "la variante no cambió ningún trade: no hay nada que medir"
        if not self.delta_pareado.significativo:
            return (
                "empate estadístico: el intervalo contiene el cero, así que la capa "
                "queda APAGADA (el default es apagada, la carga de la prueba es de la capa)"
            )
        if self.delta_pareado.media < 0:
            return "la capa EMPEORA la expectancy sobre los trades que toca: queda apagada"
        if self.menos_trades and self.ror_empeora:
            return (
                f"mejora la expectancy por trade ({self.delta_pareado.media:+.3f}R) pero con "
                f"{self.n_base - self.n_variante} trades menos y peor retorno sobre riesgo "
                f"({self.ror_base:.3f} -> {self.ror_variante:.3f}): NO es una mejora, "
                "el capital rinde menos con mejor número por trade"
            )
        return "mejora medible sobre los trades que toca; falta la validación por tramos"

    def lineas(self) -> list[str]:
        """El informe de consola del banco."""
        p = self.pareo
        return [
            f"{self.etiqueta_base}  ->  {self.etiqueta_variante}",
            "",
            f"  trades            {self.n_base} -> {self.n_variante}"
            f"   (pares {len(p.pares)}, solo base {len(p.solo_base)}, "
            f"solo variante {len(p.solo_variante)})",
            f"  trades afectados  {len(p.afectados)} de {len(p.pares)} pares"
            f"   ->  f = {self.fraccion_afectada:.3f}",
            "",
            f"  expectancy        {self.expectancy_base:+.3f}R -> {self.expectancy_variante:+.3f}R",
            f"  return_on_risk    {self.ror_base:+.3f} -> {self.ror_variante:+.3f}",
            f"  CAGR              {self.cagr_base * 100:+.2f}% -> {self.cagr_variante * 100:+.2f}%",
            f"  MDD               {self.mdd_base * 100:+.2f}% -> {self.mdd_variante * 100:+.2f}%",
            "",
            f"  delta pareado     {self.delta_pareado}",
            f"  delta sin parear  {self.delta_no_pareado}   (lo que se ve sin este banco)",
            "",
            f"  {self.veredicto()}",
        ]


def comparar(
    base: BacktestResult,
    variante: BacktestResult,
    *,
    etiqueta_base: str = "base",
    etiqueta_variante: str = "variante",
    seed: int = SEED,
    replicas: int = REPLICAS,
) -> Comparacion:
    """Compara dos corridas del motor sobre los mismos datos.

    Se miden los trades que cerró una regla: el cierre forzado por fin de datos
    no lo decidió ninguna capa y compararlo mide el calendario, no la estrategia.
    """
    trades_base = base.rule_trades
    trades_variante = variante.rule_trades
    pareo = emparejar(trades_base, trades_variante)

    return Comparacion(
        etiqueta_base=etiqueta_base,
        etiqueta_variante=etiqueta_variante,
        pareo=pareo,
        delta_pareado=bootstrap_pareado(pareo.deltas_r, seed=seed, replicas=replicas),
        delta_no_pareado=bootstrap_no_pareado(
            [t.pnl_r for t in trades_base],
            [t.pnl_r for t in trades_variante],
            seed=seed,
            replicas=replicas,
        ),
        expectancy_base=expectancy_r(trades_base),
        expectancy_variante=expectancy_r(trades_variante),
        ror_base=return_on_risk(trades_base),
        ror_variante=return_on_risk(trades_variante),
        n_base=len(trades_base),
        n_variante=len(trades_variante),
        cagr_base=float(base.metrics["cagr"]),
        cagr_variante=float(variante.metrics["cagr"]),
        mdd_base=float(base.metrics["max_drawdown"]),
        mdd_variante=float(variante.metrics["max_drawdown"]),
    )
