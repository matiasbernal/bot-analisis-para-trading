"""Las invariantes del estado de la posición abierta.

Es el piso de cuatro capas de salida (break-even, trailing, giveback, time stop),
así que lo que se prueba acá no son detalles de implementación sino las tres cosas
que esas capas van a dar por ciertas sin volver a chequearlas:

1. el stop nunca baja;
2. la unidad de riesgo se fija en la entrada y no la mueve el trailing;
3. el armado de una capa es de una sola vía.

Si alguna de estas tres se rompe, las cuatro capas se rompen juntas y el síntoma
aparece lejos de la causa.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from tradingbot.strategy.position import Position

ENTRADA = 100.0
RIESGO = 5.0  # 1R por acción: stop inicial en 95
ACCIONES = 20


def posicion(**overrides) -> Position:
    """Posición larga de 20 acciones a 100, con 1R = 5 por acción (stop en 95)."""
    kwargs = dict(
        symbol="TEST",
        entry_date=date(2020, 1, 2),
        entry_price=ENTRADA,
        shares=ACCIONES,
        risk_per_share=RIESGO,
        stop_current=ENTRADA - RIESGO,
        peak_price=ENTRADA,
    )
    kwargs.update(overrides)
    return Position(**kwargs)


# --- invariante 1: el stop nunca baja ------------------------------------
def test_el_stop_no_baja_y_lo_dice():
    pos = posicion()
    assert pos.raise_stop(98.0) is True
    assert pos.stop_current == pytest.approx(98.0)
    assert pos.stop_moves == 1

    # un trailing que propone un nivel peor no mueve nada y lo informa
    assert pos.raise_stop(96.0) is False
    assert pos.stop_current == pytest.approx(98.0)
    assert pos.stop_moves == 1


def test_proponer_el_mismo_nivel_no_cuenta_como_movimiento():
    pos = posicion()
    assert pos.raise_stop(95.0) is False
    assert pos.stop_moves == 0


def test_el_stop_inicial_queda_guardado_aunque_el_stop_se_mueva():
    pos = posicion()
    pos.raise_stop(104.0)
    assert pos.stop_initial == pytest.approx(95.0)
    assert pos.stop_current == pytest.approx(104.0)


# --- invariante 2: 1R se fija en la entrada ------------------------------
def test_mover_el_stop_no_cambia_la_unidad_de_riesgo():
    pos = posicion()
    r_antes = pos.r_multiple(110.0)
    pos.raise_stop(105.0)  # trailing bien arriba de la entrada

    assert pos.risk_per_share == pytest.approx(RIESGO)
    assert pos.r_multiple(110.0) == pytest.approx(r_antes)
    assert pos.r_multiple(110.0) == pytest.approx(2.0)  # (110-100)/5


def test_riesgo_a_la_mesa_arranca_en_1R_y_se_vuelve_negativo_con_break_even():
    pos = posicion()
    # en la entrada, con el stop inicial: lo que está en juego es exactamente 1R
    assert pos.risk_at_stake(ENTRADA) == pytest.approx(ACCIONES * RIESGO)
    assert pos.stop_r == pytest.approx(-1.0)

    # el precio sube y el stop no se movió: hay más en juego que 1R
    assert pos.risk_at_stake(110.0) == pytest.approx(ACCIONES * 15.0)

    # break-even: el stop pasa a la entrada y no queda riesgo a la mesa
    pos.raise_stop(ENTRADA)
    assert pos.stop_r == pytest.approx(0.0)
    assert pos.risk_at_stake(ENTRADA) == pytest.approx(0.0)

    # stop arriba de la entrada: el "riesgo" es negativo, o sea ganancia asegurada
    pos.raise_stop(102.0)
    assert pos.risk_at_stake(ENTRADA) < 0
    assert pos.stop_r == pytest.approx(0.4)  # (102-100)/5


# --- invariante 3: el armado es de una sola vía --------------------------
def test_el_armado_no_se_revierte_cuando_el_precio_vuelve():
    pos = posicion()
    assert pos.arm_when("trailing_stop", 1.0) is False
    assert pos.is_armed("trailing_stop") is False

    pos.update_excursions(high=106.0, low=99.0)  # pico 106 -> +1.2R
    assert pos.peak_r == pytest.approx(1.2)
    assert pos.arm_when("trailing_stop", 1.0) is True

    # el precio se da vuelta: el pico sigue siendo 106 y la capa sigue armada
    pos.update_excursions(high=101.0, low=100.0)
    assert pos.peak_r == pytest.approx(1.2)
    assert pos.arm_when("trailing_stop", 1.0) is True
    assert pos.is_armed("trailing_stop") is True


def test_sin_umbral_la_capa_esta_armada_desde_la_entrada():
    pos = posicion()
    assert pos.arm_when("break_even", None) is True
    assert pos.arm_when("giveback", 0.0) is True


def test_cada_capa_se_arma_por_su_cuenta():
    pos = posicion()
    pos.update_excursions(high=106.0, low=100.0)  # +1.2R
    assert pos.arm_when("trailing_stop", 1.0) is True
    assert pos.arm_when("giveback", 1.5) is False
    assert pos.armed == {"trailing_stop"}


# --- pico, excursiones y giveback ---------------------------------------
def test_el_pico_sigue_al_maximo_y_peak_r_es_mfe_r():
    pos = posicion()
    pos.update_excursions(high=103.0, low=97.0)
    pos.update_excursions(high=101.0, low=94.0)  # el high baja, el low hace nuevo mínimo

    assert pos.peak_price == pytest.approx(103.0)
    assert pos.trough_price == pytest.approx(94.0)
    assert pos.peak_r == pytest.approx(0.6)
    assert pos.mfe_r == pytest.approx(pos.peak_r)
    assert pos.mae_r == pytest.approx(-1.2)


def test_giveback_mide_la_fraccion_de_la_ganancia_devuelta_en_R():
    pos = posicion()
    pos.update_excursions(high=110.0, low=100.0)  # pico +2R
    assert pos.peak_r == pytest.approx(2.0)

    # el precio vuelve a +1.2R: devolvió 0.8R de 2R = 40%
    assert pos.giveback_fraction(106.0) == pytest.approx(0.4)
    # en el pico no devolvió nada
    assert pos.giveback_fraction(110.0) == pytest.approx(0.0)
    # de vuelta en la entrada devolvió todo
    assert pos.giveback_fraction(ENTRADA) == pytest.approx(1.0)


def test_sin_ganancia_el_giveback_no_es_cero_sino_indefinido():
    pos = posicion()
    pos.update_excursions(high=100.0, low=96.0)  # nunca estuvo en ganancia
    assert math.isnan(pos.giveback_fraction(97.0))


def test_giveback_de_40_por_ciento_es_mas_plata_cuanto_mas_grande_el_pico():
    """El 40% es de la ganancia, no del precio: la distancia absoluta escala."""
    chico, grande = posicion(), posicion()
    chico.update_excursions(high=105.0, low=100.0)   # pico +1R
    grande.update_excursions(high=120.0, low=100.0)  # pico +4R

    # el precio que dispara un giveback del 40% en cada caso
    assert chico.giveback_fraction(103.0) == pytest.approx(0.4)   # devolvió 0.4R
    assert grande.giveback_fraction(112.0) == pytest.approx(0.4)  # devolvió 1.6R
