"""Poder de medición: qué capas se pueden medir con este universo y este período.

El PLAN dice que cada capa de salida "se queda solo si mejora la expectancy". Eso
supone que la mejora se puede *medir*, y con treinta y pico de trades no siempre
se puede. Este módulo calcula, **antes** de escribir la capa, cuánto efecto hace
falta para distinguirla del ruido.

**Por qué es un número por capa y no uno global.** Si la capa cambia el resultado
de una fracción *f* de los trades, los deltas pareados valen cero en el resto, y
eso no es información: es relleno. Con σ el desvío del efecto entre los trades
que la capa sí toca, el desvío de la media sobre los *n* pares es σ·√(f/n), así
que el efecto mínimo detectable vale

    MDE sobre la expectancy global  = (z_{1-α/2} + z_{potencia}) · σ · √(f/n)
    MDE por trade afectado          = (z_{1-α/2} + z_{potencia}) · σ / √(f·n)

El segundo es el que decide si la capa es medible, porque es lo que la capa tiene
que lograr **en los trades que toca**. Escala con 1/√(f·n): entre una capa que
toca todos los trades y una que toca el 15% hay un factor 2.6 con el mismo
universo y el mismo período. Publicar un solo MDE global haría parecer medibles a
las capas raras, que son justo las que no lo son.

**Y con qué se compara.** Un MDE solo no dice nada: hay que ponerlo contra el
efecto que la capa *puede* llegar a tener, que sale de los trades ya cerrados
(cuánta R dejó cada uno sobre la mesa, cuánta R perdió después de haber estado en
ganancia). Si el mínimo detectable es más grande que el máximo disponible, la capa
**no se puede medir acá** y eso se dice, en vez de reportar un empate como si
fuera información.

**De dónde sale σ.** Del banco A/B, cuando la capa ya existe (``comparar`` lo
devuelve). Cuando todavía no existe —que es el caso al planificar— se usa una
proxy calibrada: sobre esta misma plantilla y este mismo universo se midieron
cuatro cambios reales de un solo parámetro (objetivo 3R→2R, 3R→4R, stop 2.0→2.5
ATR, y sacar el objetivo), y el σ entre trades afectados dio 0.96, 1.47, 1.39 y
2.55, con mediana 1.43 ≈ 0.58 × el recorrido medio de un trade (MFE − MAE = 2.46R).
De ahí ``FACTOR_SIGMA``. **Es una calibración, no una derivación**: el rango
observado va de 0.39× a 1.04× del recorrido, así que la tabla sirve para decidir
si una capa está lejos o cerca del límite, no para discutir la tercera decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from tradingbot.backtest.portfolio import Trade

ALPHA = 0.05
POTENCIA = 0.80

#: σ del efecto ≈ FACTOR_SIGMA × recorrido medio del trade. Calibrado, ver el módulo.
FACTOR_SIGMA = 0.58

#: menos trades afectados que esto y la media del efecto no significa nada, aunque el
#: MDE dé holgado: es el mismo criterio que MIN_WINNERS_FOR_CONCENTRATION en metrics.py
MIN_AFECTADOS = 10

#: los parámetros por defecto de cada capa en el PLAN, que son los que fijan la fracción
TRIGGER_BREAK_EVEN = 1.0
ACTIVA_TRAILING = 1.0
ACTIVA_GIVEBACK = 1.5
GIVEBACK_MAX_PCT = 0.40
TIME_STOP_BARS = 20
TIME_STOP_PROGRESO = 0.5
SMA_REGIMEN = 200


def factor_z(alpha: float = ALPHA, potencia: float = POTENCIA) -> float:
    """``z_{1-α/2} + z_{potencia}``. Con 5% y 80% da 2.802."""
    normal = NormalDist()
    return normal.inv_cdf(1 - alpha / 2) + normal.inv_cdf(potencia)


@dataclass(frozen=True)
class Mde:
    por_afectado: float
    sobre_expectancy: float


def mde(
    sigma: float,
    n: int,
    *,
    fraccion: float = 1.0,
    alpha: float = ALPHA,
    potencia: float = POTENCIA,
) -> Mde:
    """Efecto mínimo detectable, por trade afectado y sobre la expectancy global."""
    if n <= 0 or fraccion <= 0 or sigma <= 0:
        return Mde(float("inf"), float("inf"))
    z = factor_z(alpha, potencia)
    por_afectado = z * sigma / np.sqrt(fraccion * n)
    return Mde(float(por_afectado), float(por_afectado * fraccion))


def recorrido_medio(trades: Sequence[Trade]) -> float:
    """R que recorrió un trade típico entre su peor y su mejor momento (MFE − MAE)."""
    if not trades:
        return 0.0
    return float(np.mean([t.mfe_r - t.mae_r for t in trades]))


def sigma_a_priori(trades: Sequence[Trade]) -> float:
    """σ del efecto de una capa, estimado sin la capa. Ver el módulo: es calibrado."""
    return FACTOR_SIGMA * recorrido_medio(trades)


# --- qué fracción toca cada capa ------------------------------------------
@dataclass(frozen=True)
class Capa:
    """Una capa con su estimador de alcance sobre los trades ya cerrados."""

    nombre: str
    #: devuelve (trades alcanzados, efecto por trade alcanzado)
    alcance: Callable[[Sequence[Trade]], tuple[list[Trade], list[float]]]
    cota: str
    base: str


def _break_even(trades):
    """Solo puede cambiar trades que llegaron a +1R y terminaron perdiendo.

    Cota **inferior**: un trade que bajó hasta la entrada a mitad de camino y
    después se recuperó también habría tocado el break-even, y eso no se ve en el
    trade cerrado. El número exacto sale del banco cuando la capa exista.
    """
    tocados = [t for t in trades if t.mfe_r >= TRIGGER_BREAK_EVEN and t.pnl_r < 0]
    return tocados, [-t.pnl_r for t in tocados]


def _trailing(trades):
    """Solo puede cambiar trades que se armaron, o sea que llegaron a +1R.

    Cota **superior**: no todo trade armado retrocede lo suficiente como para que
    el trailing lo saque antes de su salida actual.
    """
    tocados = [t for t in trades if t.mfe_r >= ACTIVA_TRAILING]
    return tocados, [t.mfe_r - t.pnl_r for t in tocados]


def _giveback(trades):
    """Trades que pasaron de +1.5R y terminaron devolviendo más del 40% del pico."""
    tocados = [
        t
        for t in trades
        if t.mfe_r >= ACTIVA_GIVEBACK and t.pnl_r < (1 - GIVEBACK_MAX_PCT) * t.mfe_r
    ]
    return tocados, [(1 - GIVEBACK_MAX_PCT) * t.mfe_r - t.pnl_r for t in tocados]


def _time_stop(trades):
    """Trades que duraron más de 20 velas.

    Cota **superior**: la capa mira el progreso *a la vela 20*, y eso pide el
    estado de la posición barra a barra, que el trade cerrado no guarda. El efecto
    se estima como cerrar en cero al vencer el plazo.
    """
    tocados = [t for t in trades if t.bars_held > TIME_STOP_BARS]
    return tocados, [-t.pnl_r for t in tocados]


CAPAS: list[Capa] = [
    Capa("trailing_stop", _trailing, "superior", f"trades con MFE ≥ {ACTIVA_TRAILING}R (armados)"),
    Capa(
        "break_even",
        _break_even,
        "inferior",
        f"trades con MFE ≥ {TRIGGER_BREAK_EVEN}R que terminaron perdiendo",
    ),
    Capa(
        "giveback",
        _giveback,
        "inferior",
        f"trades con MFE ≥ {ACTIVA_GIVEBACK}R que devolvieron ≥{GIVEBACK_MAX_PCT:.0%} del pico",
    ),
    Capa("time_stop", _time_stop, "superior", f"trades de más de {TIME_STOP_BARS} velas"),
]


def regimen_bajista(spy: pd.DataFrame, periodo: int = SMA_REGIMEN) -> pd.Series:
    """``SPY_close < SPY_sma_200``, que es la regla de régimen del PLAN."""
    close = spy["close"].astype("float64")
    return close < close.rolling(periodo).mean()


def _market_regime(trades: Sequence[Trade], spy: pd.DataFrame):
    """Entradas que el filtro de régimen no habría dejado tomar.

    Es **exacto**, no una cota: el filtro mira SPY el día de la señal y con eso
    alcanza. Se evalúa el día anterior a la entrada, que es cuando se decide
    (señal al cierre de t, fill en la apertura de t+1).
    """
    bajista = regimen_bajista(spy)
    fechas = bajista.index
    tocados = []
    for t in trades:
        previas = fechas[fechas < pd.Timestamp(t.entry_date)]
        if len(previas) and bool(bajista.loc[previas[-1]]):
            tocados.append(t)
    return tocados, [-t.pnl_r for t in tocados]


# --- la tabla publicada ----------------------------------------------------
@dataclass(frozen=True)
class Poder:
    capa: str
    n: int
    n_afectados: int
    fraccion: float
    sigma: float
    mde_afectado: float
    mde_expectancy: float
    efecto_disponible: float
    cota: str
    base: str

    @property
    def exigencia(self) -> float:
        """Qué fracción del efecto disponible tiene que capturar la capa para verse.

        Es el número que convierte el MDE en una pregunta contestable: no "¿es
        medible?" sino "¿es creíble que esta capa capture el 65% de toda la R que
        hay sobre la mesa, en cada trade que toca?".
        """
        if self.efecto_disponible <= 0 or not np.isfinite(self.mde_afectado):
            return float("inf")
        return self.mde_afectado / self.efecto_disponible

    @property
    def medible(self) -> bool:
        """Hay margen: el efecto disponible supera el mínimo detectable.

        Es condición necesaria y no suficiente. El efecto disponible es el **mejor
        caso** —capturar toda la R que el trade dejó sobre la mesa— y ninguna capa
        real captura todo: un trailing chandelier devuelve 3 ATR antes de sacarte.
        Por eso el veredicto se expresa como exigencia y no como un sí.
        """
        return (
            self.n_afectados >= MIN_AFECTADOS
            and np.isfinite(self.mde_afectado)
            and self.efecto_disponible >= self.mde_afectado
        )

    @property
    def veredicto(self) -> str:
        if self.n_afectados == 0:
            return "no toca ningún trade acá"
        if self.n_afectados < MIN_AFECTADOS:
            return (
                f"NO medible: {self.n_afectados} trades afectados "
                f"(hacen falta {MIN_AFECTADOS} para que la media signifique algo)"
            )
        if not self.medible:
            return "NO medible: ni capturando todo el efecto disponible se distingue del ruido"
        return f"necesita capturar el {self.exigencia:.0%} del efecto disponible"


def poder_por_capa(
    trades: Sequence[Trade],
    *,
    spy: pd.DataFrame | None = None,
    sigma: float | None = None,
) -> list[Poder]:
    """Una fila por capa: su fracción, su mínimo detectable y su efecto disponible."""
    trades = list(trades)
    n = len(trades)
    sigma = sigma if sigma is not None else sigma_a_priori(trades)

    capas = list(CAPAS)
    filas: list[Poder] = []
    for capa in capas:
        tocados, efectos = capa.alcance(trades)
        filas.append(_fila(capa.nombre, trades, tocados, efectos, sigma, capa.cota, capa.base))

    if spy is not None and not spy.empty:
        tocados, efectos = _market_regime(trades, spy)
        filas.append(
            _fila(
                "market_regime",
                trades,
                tocados,
                efectos,
                sigma,
                "exacta",
                f"entradas con SPY < SMA{SMA_REGIMEN}",
            )
        )
    return filas


def _fila(nombre, trades, tocados, efectos, sigma, cota, base) -> Poder:
    n = len(trades)
    fraccion = len(tocados) / n if n else 0.0
    valor = mde(sigma, n, fraccion=fraccion)
    return Poder(
        capa=nombre,
        n=n,
        n_afectados=len(tocados),
        fraccion=fraccion,
        sigma=sigma,
        mde_afectado=valor.por_afectado,
        mde_expectancy=valor.sobre_expectancy,
        efecto_disponible=float(np.mean(np.abs(efectos))) if efectos else 0.0,
        cota=cota,
        base=base,
    )


#: capas que no se pueden estimar sin escribirlas o sin datos que el entorno no tiene
SIN_ESTIMAR = {
    "reversal": (
        "no estimable sin la capa: depende de siete señales que todavía no existen. "
        "Su f la mide el banco cuando la capa esté escrita"
    ),
    "event_risk": (
        "no estimable sin red: necesita fechas de earnings (Ticker.earnings_dates). "
        "Queda fuera del torneo por decisión escrita en el PLAN"
    ),
}


def curva_de_poder(
    trades: Sequence[Trade],
    *,
    fracciones: Sequence[float] = (1.0, 0.75, 0.50, 0.25, 0.15),
    sigma: float | None = None,
) -> list[tuple[float, Mde]]:
    """El MDE como función de la fracción de trades afectados, sin atarlo a una capa."""
    trades = list(trades)
    sigma = sigma if sigma is not None else sigma_a_priori(trades)
    return [(f, mde(sigma, len(trades), fraccion=f)) for f in fracciones]


def trades_necesarios(
    objetivo: float,
    *,
    sigma: float,
    fraccion: float = 1.0,
    alpha: float = ALPHA,
    potencia: float = POTENCIA,
) -> int:
    """Cuántos trades harían falta para detectar ``objetivo`` R por trade afectado."""
    if objetivo <= 0 or sigma <= 0 or fraccion <= 0:
        return 0
    z = factor_z(alpha, potencia)
    return int(np.ceil((z * sigma / objetivo) ** 2 / fraccion))


def poder_lineas(
    trades: Sequence[Trade],
    *,
    spy: pd.DataFrame | None = None,
    sigma: float | None = None,
) -> list[str]:
    """El bloque de consola. Es lo que el DoD de la tanda 2A pide publicar."""
    trades = list(trades)
    n = len(trades)
    if n == 0:
        return ["PODER DE MEDICIÓN", "  sin trades: no hay nada que medir"]

    sigma_valor = sigma if sigma is not None else sigma_a_priori(trades)
    medido = sigma is not None

    lineas = [
        "PODER DE MEDICIÓN — cuánto efecto hace falta para distinguir una capa del ruido",
        f"  n = {n} trades · σ del efecto = {sigma_valor:.2f}R "
        f"({'medida por el banco' if medido else 'estimada, ver poder.py'}) · "
        f"α = {ALPHA:.2f} · potencia = {POTENCIA:.0%}",
        "",
        "  fracción de trades      MDE por trade      MDE sobre la",
        "  que la capa toca         afectado          expectancy global",
    ]
    for fraccion, valor in curva_de_poder(trades, sigma=sigma_valor):
        lineas.append(
            f"       {fraccion * 100:5.0f}%              {valor.por_afectado:6.2f}R"
            f"              {valor.sobre_expectancy:6.2f}R"
        )

    filas = poder_por_capa(trades, spy=spy, sigma=sigma_valor)
    lineas += [
        "",
        "  capa             afect    f     MDE/afect  disponible  cota       veredicto",
    ]
    for fila in filas:
        lineas.append(
            f"  {fila.capa:<15} {fila.n_afectados:>4}  {fila.fraccion:5.2f}  "
            f"{fila.mde_afectado:8.2f}R  {fila.efecto_disponible:8.2f}R  "
            f"{fila.cota:<9}  {fila.veredicto}"
        )
    for capa, motivo in SIN_ESTIMAR.items():
        lineas.append(f"  {capa:<15}    —      —          —           —      —          {motivo}")

    lineas += [
        "",
        "  trailing_stop NO es candidata del torneo: entra por decisión de diseño del PLAN",
        "  (línea base de las plantillas). Su fila está para dimensionar, no para decidir:",
        "  con este universo y este período el poder no alcanza para afirmar que aporta.",
        "",
        "  'disponible' es el **mejor caso** de la capa sobre los trades que toca, medido",
        "  sobre los trades ya cerrados: capturar toda la R que quedó sobre la mesa. Ninguna",
        "  capa real captura todo (un chandelier devuelve 3 ATR antes de sacarte), así que el",
        "  veredicto se lee como exigencia: si dice 65%, la capa tiene que capturar dos tercios",
        "  de todo lo disponible para que el resultado se distinga de un empate.",
    ]
    return lineas


# --- proyección a otro universo -------------------------------------------
#: trades esperables con datos reales: 15 años x 10 símbolos a la frecuencia de
#: señal de la plantilla (~1.5 trades por símbolo-año, medida sobre los dos
#: fixtures). Es el universo que la Fase 3 va a tener cuando haya CSV reales, y
#: el número con el que el PLAN calcula cuántas capas quedan sin poder.
N_UNIVERSO_REAL = 230


def proyectar(filas: Sequence[Poder], n_objetivo: int) -> list[Poder]:
    """Las mismas capas, con el MDE recalculado para un universo de otro tamaño.

    Lo que se conserva de cada fila es lo que **no** depende de cuántos trades
    haya: la fracción de trades que la capa toca y el efecto disponible por trade
    afectado, que son propiedades por trade. Lo que se recalcula es el mínimo
    detectable, que escala con 1/√(f·n), y la cantidad de trades afectados.

    Sirve para contestar "¿alcanza con los datos reales?" **antes** de tenerlos, y
    con eso decidir el alcance del torneo en vez de descubrirlo al final. Lo que
    no hace es adivinar cómo cambian f, σ y el efecto disponible sobre datos de
    mercado: los tres salen del fixture sintético y ahí valen lo que dice la
    etiqueta de alcance de ESTADO.md. La proyección es aritmética sobre n, no un
    pronóstico sobre el mercado.
    """
    proyectadas: list[Poder] = []
    for fila in filas:
        valor = mde(fila.sigma, n_objetivo, fraccion=fila.fraccion)
        proyectadas.append(
            Poder(
                capa=fila.capa,
                n=n_objetivo,
                n_afectados=int(round(fila.fraccion * n_objetivo)),
                fraccion=fila.fraccion,
                sigma=fila.sigma,
                mde_afectado=valor.por_afectado,
                mde_expectancy=valor.sobre_expectancy,
                efecto_disponible=fila.efecto_disponible,
                cota=fila.cota,
                base=fila.base,
            )
        )
    return proyectadas
