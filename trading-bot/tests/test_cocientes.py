"""La regla del cociente inestable, con los tres casos reales que la motivaron.

No son ejemplos inventados: los tres números están tomados de informes que este
repo imprimió (252%, 426%, 118%) y que se arreglaron por separado antes de que
alguien notara que era el mismo error tres veces.
"""

from __future__ import annotations

import math

import pytest

from tradingbot.backtest.cocientes import (
    PISO_CAGR,
    PISO_CUENTA,
    PISO_PESOS_SOBRE_R,
    contra_piso,
)
from tradingbot.backtest.metrics import (
    MIN_WINNERS_FOR_CONCENTRATION,
    concentration_baseline,
    top_trades_concentration,
    win_loss_ratio,
)
from tradingbot.backtest.poder import MIN_AFECTADOS
from test_metrics import trade  # el mismo trade a mano que usa test_metrics.py


def test_con_el_denominador_holgado_el_cociente_se_publica():
    c = contra_piso(120.0, 100.0, piso=10.0)
    assert c.publicable
    assert c.desvio_relativo == pytest.approx(0.20)
    assert c.diferencia == pytest.approx(20.0)


def test_con_el_denominador_bajo_el_piso_no_se_publica_y_queda_la_diferencia():
    """El caso de la lectura ingenua: $3.52 contra $0.67 son 426%, y no significa nada."""
    c = contra_piso(3.52, 0.67, piso=PISO_PESOS_SOBRE_R * 91.41)

    assert not c.publicable
    assert math.isnan(c.desvio_relativo), "el desvío no se puede publicar"
    assert c.diferencia == pytest.approx(2.85, abs=0.01), "la diferencia sí"

    # y para que quede claro cuál era el número prohibido
    assert abs(3.52 / 0.67 - 1) * 100 == pytest.approx(425.4, abs=0.5)


def test_el_piso_en_pesos_sale_de_la_escala_del_trade_y_no_de_un_numero_redondo():
    """5% del 1R realizado. Con 1R = $91.41 el piso queda en $4.57."""
    piso = PISO_PESOS_SOBRE_R * 91.41
    assert piso == pytest.approx(4.57, abs=0.01)

    # ema_cross v3: expectancy en plata $0.67 -> debajo del piso, no publica
    assert not contra_piso(3.52, 0.67, piso=piso).publicable
    # la plantilla de Bollinger: $5.11 -> arriba del piso, publica (y por poco)
    assert contra_piso(6.0, 5.11, piso=piso).publicable


def test_el_piso_de_cagr_es_el_que_salva_el_cotejo_de_msft():
    """118% de diferencia sobre 30 puntos básicos: la diferencia absoluta era 0.03%."""
    nuestro, suyo = 0.0033, 0.0030
    c = contra_piso(nuestro, suyo, piso=PISO_CAGR)

    assert not c.publicable, "un CAGR de 0.30% no aguanta un cociente"
    assert abs(c.diferencia) < PISO_CAGR
    assert abs(nuestro / suyo - 1) * 100 == pytest.approx(10.0, abs=0.1)

    # con CAGR de verdad el cociente vuelve a servir
    assert contra_piso(0.118, 0.100, piso=PISO_CAGR).publicable


def test_un_denominador_que_contiene_al_numerador_no_necesita_piso():
    """La opción 1 de la regla, que es la que se usó con la concentración.

    Dividiendo por la ganancia BRUTA el cociente vive en [0, 1] por construcción,
    pase lo que pase con el P&L neto. Dividiendo por el neto daba 252%.
    """
    ganancias = [500.0, 300.0, 200.0, 100.0, 50.0, 40.0]
    perdidas = [-1000.0]
    trades = [trade(p, dia=i) for i, p in enumerate(ganancias + perdidas)]

    bruta = top_trades_concentration(trades)
    assert 0.0 <= bruta <= 1.0

    neto = sum(ganancias + perdidas)
    assert neto == pytest.approx(190.0)
    # el número viejo, para que se vea por qué se cambió el denominador: los 5
    # mejores sobre el neto dan 605%, y con el neto negativo daría signo cambiado
    assert sum(sorted(ganancias, reverse=True)[:5]) / neto == pytest.approx(6.05, abs=0.01)


def test_los_tres_pisos_de_cuenta_son_el_mismo_numero():
    """Un piso repetido en tres módulos es tres pisos que se pueden desincronizar."""
    assert MIN_WINNERS_FOR_CONCENTRATION == PISO_CUENTA
    assert MIN_AFECTADOS == PISO_CUENTA


def test_la_concentracion_se_compara_contra_su_normal_y_no_contra_un_umbral_fijo():
    """La consecuencia de la regla: el valor normal depende de n."""
    assert concentration_baseline(6) > 0.95, "con 6 ganadores los 5 mejores son casi todo"
    assert concentration_baseline(50) < 0.40, "con 50 no"
    # un umbral fijo de 80% saltaría siempre en el primer caso y nunca en el segundo


def test_sin_perdedores_los_dos_cocientes_hermanos_contestan_lo_mismo():
    """``win_loss_ratio`` devolvía 0.0, que se imprime '0.00' y se lee al revés."""
    solo_ganadores = [trade(100.0, dia=1), trade(50.0, dia=2)]
    assert win_loss_ratio(solo_ganadores) == float("inf")

    solo_perdedores = [trade(-100.0, dia=1)]
    assert win_loss_ratio(solo_perdedores) == 0.0, "sin ganadores el cero SÍ es correcto"

    assert win_loss_ratio([]) == 0.0
