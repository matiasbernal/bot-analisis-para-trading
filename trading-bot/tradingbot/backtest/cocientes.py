"""La regla del cociente inestable, en un solo lugar.

Tres veces en este proyecto apareció el mismo error con tres caras distintas, y
las tres veces se arregló por separado antes de que alguien notara que era el
mismo error:

| Dónde | Qué se publicaba | Por qué era ruido |
|---|---|---|
| concentración del resultado | **252%** de los 5 mejores | dividía por el P&L **neto**, que es la resta de dos números grandes y puede quedar en cualquier cosa (o negativo) |
| error de la lectura ingenua | **426%** de desvío | dividía por la expectancy en plata, que con una estrategia empatada vale $0.67 |
| cotejo contra ``backtesting.py`` | **118%** de diferencia de CAGR | dividía por un CAGR de 30 puntos básicos: la diferencia absoluta era media décima de punto |

En los tres el numerador estaba bien medido y el resultado no significaba nada,
porque **un cociente hereda la estabilidad de su denominador**. Un denominador
chico no achica el error: lo amplifica y le pone cara de porcentaje, que es peor
que no publicarlo, porque un porcentaje se lee como una medición.

---

## La regla, en orden de preferencia

1. **Elegir un denominador que contenga al numerador.** Si ``B ⊇ A`` por
   construcción, el cociente vive en ``[0, 1]`` y no puede explotar, sin
   necesidad de ningún piso. Es lo que se hizo con la concentración: ganancia
   **bruta** en vez de P&L neto. Cuando esta opción existe, es la mejor, porque
   no tiene parámetro que calibrar.

2. **Si no se puede, exigir un piso explícito sobre ``|B|``**, atado a la escala
   natural del denominador y no a un número redondo elegido a ojo. Los tres
   pisos que usa el proyecto están abajo, cada uno con de dónde sale.

3. **Debajo del piso se publica la diferencia absoluta ``A − B`` con su unidad**,
   y **se dice por qué** no está el porcentaje. Callar el número sería peor: el
   lector no sabría si la diferencia es chica o si el informe la escondió.

Y una consecuencia que no es obvia: **un cociente cuyo valor "normal" depende del
tamaño de la muestra se compara contra su propia normal para ese n**, no contra
un umbral fijo. Los 5 mejores de 6 ganadores son el 98% por aritmética y los de
50 son el 32%: un umbral de 80% mide cuántos trades hay, no concentración. Por
eso ``concentration_ratio`` divide por ``concentration_baseline(n)``.

## Cuando el fallback tampoco sirve

Para algunos cocientes la diferencia absoluta no significa nada (``CAGR − MDD``
no es una cantidad). Ahí el paso 3 es **no publicar el cociente y dejar los dos
componentes en sus propias filas**, que el informe ya trae. Es el caso de Calmar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Piso para un denominador en PESOS por trade (la expectancy en plata).
#: Sale de la escala del propio trade: el 5% del 1R realizado medio. Por debajo
#: de eso la expectancy no se distingue de cero con la cantidad de trades que
#: produce cualquier corrida de este repo, así que el cociente mide ruido. Con
#: 1R ≈ $91 el piso queda en ~$4.57; ema_cross v3 tiene $0.67 (no publica) y la
#: plantilla de Bollinger $5.11 (publica, y por poco).
PISO_PESOS_SOBRE_R = 0.05

#: Piso para un denominador que es un CAGR: media décima de punto anual. Sale de
#: que por debajo de eso la diferencia entre dos motores es del orden del
#: redondeo del propio cálculo. Lo usa ``tests/test_vs_backtesting.py``.
PISO_CAGR = 0.005

#: Piso para un denominador que es una CUENTA (ganadores, trades afectados por
#: una capa): diez. Por debajo, la media de la que sale el cociente es una media
#: de menos de diez números y el cociente hereda esa varianza. Es el mismo diez
#: de ``MIN_WINNERS_FOR_CONCENTRATION`` y de ``MIN_AFECTADOS``.
PISO_CUENTA = 10


@dataclass(frozen=True)
class Cociente:
    """El resultado de aplicar la regla: el cociente, o la diferencia y el motivo.

    Se devuelve siempre la diferencia, publicable o no, porque es el número que
    va en el informe cuando el porcentaje no se puede publicar.
    """

    numerador: float
    denominador: float
    piso: float

    @property
    def publicable(self) -> bool:
        """¿El denominador aguanta el peso del cociente?"""
        return (
            math.isfinite(self.numerador)
            and math.isfinite(self.denominador)
            and abs(self.denominador) >= self.piso
            and self.piso > 0
        )

    @property
    def diferencia(self) -> float:
        """``A − B``, en la unidad de los dos. Siempre disponible."""
        return self.numerador - self.denominador

    @property
    def desvio_relativo(self) -> float:
        """``|A/B − 1|``, o ``nan`` si el denominador no aguanta.

        Devuelve ``nan`` y no el número "por las dudas": si alguien lo imprime
        sin mirar ``publicable``, un ``nan`` en el informe se ve, y un 426% no.
        """
        if not self.publicable or self.denominador == 0:
            return float("nan")
        return abs(self.numerador / self.denominador - 1.0)


def contra_piso(numerador: float, denominador: float, piso: float) -> Cociente:
    """Aplica la regla. ``piso`` va explícito en la llamada, a propósito.

    No hay default: el piso depende de la escala del denominador y elegirlo es
    la decisión que la regla obliga a tomar. Un default lo escondería.
    """
    return Cociente(float(numerador), float(denominador), float(piso))
