"""Tests de la aritmética de ``scripts/universo.py``.

La tabla que decide el universo se apoya en cuatro cuentas: cuántos símbolo-año
útiles tiene una opción, cuántos trades son a un ritmo dado, dónde está el techo
que pone el cupo de cartera y cuántos trades pide cada capa para una exigencia
dada. Ninguna es complicada y las cuatro son fáciles de equivocar en un factor
de dos, que acá es la diferencia entre "alcanza" y "no alcanza".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tradingbot.backtest.poder import Poder

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import universo  # noqa: E402


def opcion(simbolos: int, historia_corta=None) -> universo.Opcion:
    return universo.Opcion(
        nombre="prueba", simbolos=simbolos, historia_corta=historia_corta or {}, sesgo=""
    )


def fila(fraccion: float, disponible: float, sigma: float = 1.20) -> Poder:
    return Poder(
        capa="prueba",
        n=75,
        n_afectados=int(75 * fraccion),
        fraccion=fraccion,
        sigma=sigma,
        mde_afectado=0.0,
        mde_expectancy=0.0,
        efecto_disponible=disponible,
        cota="superior",
        base="",
    )


# --- símbolo-años ---------------------------------------------------------
def test_el_warmup_se_descuenta_una_vez_por_simbolo_no_una_vez_por_anio():
    """200 velas de warmup cuestan 0.79 años por símbolo, no 0.79 por símbolo-año."""
    util = universo.simbolo_anios_utiles(opcion(10), anios=15.0, warmup_bars=200)

    assert util == pytest.approx(10 * (15 - 200 / 252), rel=1e-9)
    assert util > 10 * 14  # el warmup se come menos de un año por símbolo


def test_sobre_quince_anios_el_warmup_pesa_un_tercio_de_lo_que_pesa_sobre_cinco():
    """Es el argumento de por qué la misma plantilla rinde más sobre 15 años."""
    quince = universo.simbolo_anios_utiles(opcion(1), anios=15.0, warmup_bars=200)
    cinco = universo.simbolo_anios_utiles(opcion(1), anios=5.0, warmup_bars=200)

    assert (15 - quince) / 15 == pytest.approx((5 - cinco) / 5 / 3, rel=0.01)


def test_un_simbolo_con_historia_corta_aporta_menos():
    """XLRE cotiza desde 2015: no tiene los 15 años y eso se cuenta."""
    completo = universo.simbolo_anios_utiles(opcion(13), anios=15.0, warmup_bars=200)
    con_xlre = universo.simbolo_anios_utiles(
        opcion(13, {"XLRE": 10.0}), anios=15.0, warmup_bars=200
    )

    assert completo - con_xlre == pytest.approx(5.0)


def test_un_simbolo_sin_historia_para_el_warmup_no_aporta_negativo():
    assert universo.simbolo_anios_utiles(opcion(3, {"NUEVO": 0.5}), 15.0, 200) > 0
    assert universo.simbolo_anios_utiles(opcion(1, {"NUEVO": 0.5}), 15.0, 200) == 0.0


def test_n_esperado_es_simbolo_anios_por_ritmo():
    n = universo.n_esperado(opcion(13), anios=15.0, ritmo=1.80, warmup_bars=200)

    assert n == round(13 * (15 - 200 / 252) * 1.80)


# --- techo por cupo -------------------------------------------------------
def test_el_cupo_pone_un_techo_que_no_depende_del_universo():
    """5 posiciones × 15 años / 17 velas de duración ≈ 1141 trades, haya 13 símbolos o 40."""
    techo = universo.techo_por_cupo(max_open=5, duracion_bars=17.0, anios=15.0)

    assert techo == round(5 * (252 / 17) * 15)
    assert 1100 < techo < 1200


def test_trades_mas_largos_bajan_el_techo():
    corto = universo.techo_por_cupo(5, duracion_bars=10.0, anios=15.0)
    largo = universo.techo_por_cupo(5, duracion_bars=40.0, anios=15.0)

    assert corto == pytest.approx(largo * 4, rel=0.01)


def test_duracion_cero_no_da_un_techo_infinito():
    assert universo.techo_por_cupo(5, duracion_bars=0.0, anios=15.0) == 0


# --- exigencia ------------------------------------------------------------
def test_bajar_la_exigencia_a_la_mitad_cuadruplica_los_trades():
    """El MDE va con 1/√(f·n): pedir la mitad del efecto pide cuatro veces los trades."""
    una = universo.n_para_exigencia(fila(0.25, 1.00), 0.66)
    media = universo.n_para_exigencia(fila(0.25, 1.00), 0.33)

    assert media == pytest.approx(una * 4, rel=0.02)


def test_una_capa_que_toca_menos_trades_pide_mas():
    """Entre f=1.0 y f=0.15 hay un factor 6.7 en trades (2.6 en MDE)."""
    todas = universo.n_para_exigencia(fila(1.00, 1.00), 0.50)
    raras = universo.n_para_exigencia(fila(0.15, 1.00), 0.50)

    assert raras == pytest.approx(todas / 0.15, rel=0.02)


def test_una_capa_sin_efecto_disponible_no_pide_un_numero_sino_nada():
    """Si no hay R sobre la mesa no hay exigencia que valga: no es 'infinitos trades'."""
    assert universo.n_para_exigencia(fila(0.25, 0.0), 0.50) == 0


def test_el_orden_de_las_capas_por_exigencia_es_el_esperado():
    """La que toca poco y tiene poco disponible (break_even) es siempre la última."""
    break_even = universo.n_para_exigencia(fila(0.19, 0.27), 0.50)
    time_stop = universo.n_para_exigencia(fila(0.25, 1.02), 0.50)
    trailing = universo.n_para_exigencia(fila(0.53, 1.39), 0.50)

    assert trailing < time_stop < break_even


# --- tamaño en disco ------------------------------------------------------
def test_redondear_a_cuatro_decimales_achica_la_fila_casi_a_la_mitad():
    crudo = universo.bytes_por_fila(None)
    redondeado = universo.bytes_por_fila(4)

    assert crudo > redondeado > 40
    assert 1.4 < crudo / redondeado < 2.0


def test_el_ancho_medido_coincide_con_los_fixtures_que_ya_estan():
    """Los sintéticos están a 4 decimales: la medición tiene que darles la razón."""
    fixture = next((universo.FIXTURES / "correlated").glob("*.csv"))
    lineas = fixture.read_text(encoding="utf-8").splitlines()
    real = (fixture.stat().st_size - len(lineas[0]) - 1) / (len(lineas) - 1)

    assert universo.bytes_por_fila(4) == pytest.approx(real, rel=0.15)


def test_las_filas_totales_cuentan_la_historia_corta():
    completo = universo.filas_totales(opcion(13), anios=15.0)
    con_xlre = universo.filas_totales(opcion(13, {"XLRE": 10.0}), anios=15.0)

    assert completo == 13 * 15 * universo.VELAS_POR_ANIO
    assert completo - con_xlre == 5 * universo.VELAS_POR_ANIO
