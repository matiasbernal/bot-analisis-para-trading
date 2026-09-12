"""El banco de comparación A/B: que mida, que no invente, y que sea reproducible.

Es el instrumento con el que se va a decidir qué capa de salida queda prendida,
así que antes de usarlo hay que probarlo contra casos donde la respuesta se sabe
de antemano:

* dos corridas idénticas tienen que dar cero, no "casi cero";
* un efecto constante sobre trades ruidosos tiene que salir del pareo y **no**
  de la comparación de frente (es la razón de existir del módulo);
* ruido simétrico no tiene que producir un efecto;
* las dos reglas de desempate del PLAN tienen que estar en el veredicto y no en
  la cabeza del que lee.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest
from conftest import make_strategy

from tradingbot.backtest.ab import (
    Comparacion,
    Pareo,
    bootstrap_no_pareado,
    bootstrap_pareado,
    comparar,
    emparejar,
)
from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.portfolio import Trade

INICIO = date(2020, 1, 2)


def trade(
    *,
    symbol: str = "TEST",
    dia_entrada: int = 0,
    pnl_r: float = 0.0,
    dia_salida: int = 10,
    exit_price: float = 110.0,
    reason: str = "take_profit",
) -> Trade:
    """Un trade a mano, con lo justo para el pareo y el delta."""
    return Trade(
        symbol=symbol,
        entry_date=INICIO + timedelta(days=dia_entrada),
        entry_price=100.0,
        shares=10,
        risk_per_share=10.0,
        stop_initial=90.0,
        exit_date=INICIO + timedelta(days=dia_salida),
        exit_price=exit_price,
        exit_reasons=[reason],
        pnl=pnl_r * 100.0,
        pnl_r=pnl_r,
        bars_held=dia_salida - dia_entrada,
        mae_r=-0.5,
        mfe_r=1.5,
        commission=0.0,
        slippage=0.0,
    )


# --- el caso que prueba que el banco no inventa efectos -------------------
def test_dos_corridas_identicas_dan_exactamente_cero(universe_frames):
    config = make_strategy(
        universe=sorted(universe_frames),
        warmup_bars=20,
        entry={"all": [{"left": "close", "op": ">", "right": 50}]},
    )
    base = run_backtest(config, universe_frames)
    otra = run_backtest(config, universe_frames)

    comp = comparar(base, otra)

    assert comp.n_base == comp.n_variante > 0
    assert len(comp.pareo.pares) == comp.n_base
    assert comp.pareo.afectados == []
    assert comp.fraccion_afectada == 0.0
    assert comp.delta_pareado.media == 0.0
    assert (comp.delta_pareado.lo, comp.delta_pareado.hi) == (0.0, 0.0)
    assert comp.delta_pareado.p_valor == 1.0
    assert "no cambió ningún trade" in comp.veredicto()


def test_una_variante_real_cambia_las_salidas_y_el_banco_lo_ve(universe_frames):
    """Objetivo a 2R en vez de 3R: misma entrada, salidas distintas."""
    comun = dict(
        universe=sorted(universe_frames),
        warmup_bars=20,
        entry={"all": [{"left": "close", "op": ">", "right": 50}]},
    )
    base = run_backtest(make_strategy(**comun), universe_frames)
    variante = run_backtest(
        make_strategy(**comun, exits={"take_profit": {"mode": "rr", "ratio": 2.0}}),
        universe_frames,
    )

    comp = comparar(base, variante, etiqueta_base="rr=3", etiqueta_variante="rr=2")

    assert comp.pareo.afectados, "un objetivo más cercano tiene que cambiar salidas"
    assert 0.0 < comp.fraccion_afectada <= 1.0
    # el pareo no descarta en silencio: todo trade está en alguno de los tres grupos
    total = (
        len(comp.pareo.pares) + len(comp.pareo.solo_base) + len(comp.pareo.solo_variante)
    )
    assert total == comp.n_base + len(comp.pareo.solo_variante)
    assert "\n".join(comp.lineas()).count("rr=") >= 1


# --- por qué el pareo y no la comparación de frente ----------------------
def test_el_pareo_encuentra_un_efecto_que_la_comparacion_de_frente_no_ve():
    """La razón de existir del módulo, con números.

    Treinta trades ruidosos (desvío ~1.4R) y una capa que le suma 0.15R a cada
    uno. Pareado el efecto es nítido; de frente, 0.15R contra 1.4R de desvío es
    indistinguible del ruido. Es exactamente el error que se comete al mirar dos
    expectancies y decidir.
    """
    rng = np.random.default_rng(1)
    base_r = rng.normal(0.2, 1.4, size=30)
    variante_r = base_r + 0.15

    pareado = bootstrap_pareado(variante_r - base_r, seed=7)
    de_frente = bootstrap_no_pareado(base_r, variante_r, seed=7)

    assert pareado.significativo
    assert pareado.media == pytest.approx(0.15)
    assert not de_frente.significativo
    assert abs(de_frente.hi - de_frente.lo) > 10 * abs(pareado.hi - pareado.lo)


def test_ruido_simetrico_no_produce_efecto():
    rng = np.random.default_rng(2)
    deltas = rng.normal(0.0, 0.5, size=40)

    resultado = bootstrap_pareado(deltas, seed=3)

    assert not resultado.significativo
    assert resultado.lo < 0 < resultado.hi
    assert resultado.p_valor > 0.05


def test_el_intervalo_se_angosta_con_mas_trades():
    """El poder depende de n: es la base del cálculo de efecto mínimo detectable."""
    rng = np.random.default_rng(4)
    chico = bootstrap_pareado(rng.normal(0.1, 1.0, size=20), seed=5)
    grande = bootstrap_pareado(rng.normal(0.1, 1.0, size=500), seed=5)

    assert (grande.hi - grande.lo) < (chico.hi - chico.lo) / 3


def test_el_banco_es_reproducible():
    deltas = [0.3, -0.1, 0.5, 0.2, -0.4, 0.9, 0.1, 0.0, 0.2, -0.2]
    uno = bootstrap_pareado(deltas, seed=99)
    otro = bootstrap_pareado(deltas, seed=99)
    distinto = bootstrap_pareado(deltas, seed=100)

    assert (uno.media, uno.lo, uno.hi, uno.p_valor) == (
        otro.media,
        otro.lo,
        otro.hi,
        otro.p_valor,
    )
    assert uno.media == distinto.media  # la media no depende de la semilla
    assert (uno.lo, uno.hi) != (distinto.lo, distinto.hi) or uno.n < 5


# --- emparejamiento -------------------------------------------------------
def test_los_trades_que_no_estan_en_las_dos_corridas_se_reportan_aparte():
    base = [trade(dia_entrada=0), trade(dia_entrada=5, symbol="OTRO")]
    variante = [trade(dia_entrada=0), trade(dia_entrada=9, symbol="NUEVO")]

    pareo = emparejar(base, variante)

    assert len(pareo.pares) == 1
    assert [t.symbol for t in pareo.solo_base] == ["OTRO"]
    assert [t.symbol for t in pareo.solo_variante] == ["NUEVO"]
    # un trade que solo existe en una corrida es efecto de la capa, así que cuenta
    assert pareo.fraccion_afectada == pytest.approx(2 / 3)


def test_un_par_con_la_misma_salida_no_cuenta_como_afectado():
    par = [trade(dia_entrada=0, pnl_r=1.0)]
    pareo = emparejar(par, [trade(dia_entrada=0, pnl_r=1.0)])
    assert pareo.afectados == []

    # misma fecha y mismo precio, distinto motivo: sí es un cambio
    otro = emparejar(par, [trade(dia_entrada=0, pnl_r=1.0, reason="trailing_stop")])
    assert len(otro.afectados) == 1


def test_un_trade_repetido_es_un_error_y_no_se_elige_uno_en_silencio():
    repetidos = [trade(dia_entrada=0), trade(dia_entrada=0)]
    with pytest.raises(ValueError, match="repetido"):
        emparejar(repetidos, [])
    with pytest.raises(ValueError, match="repetido"):
        emparejar([], repetidos)


# --- las dos reglas de desempate -----------------------------------------
def comparacion(*, delta, n_base, n_variante, ror_base, ror_variante, afectados=3):
    pareo = Pareo(pares=[(trade(dia_entrada=i), trade(dia_entrada=i, reason="trailing_stop"))
                         for i in range(afectados)])
    return Comparacion(
        etiqueta_base="base",
        etiqueta_variante="variante",
        pareo=pareo,
        delta_pareado=delta,
        delta_no_pareado=delta,
        expectancy_base=0.3,
        expectancy_variante=0.3 + delta.media,
        ror_base=ror_base,
        ror_variante=ror_variante,
        n_base=n_base,
        n_variante=n_variante,
        cagr_base=0.03,
        cagr_variante=0.04,
        mdd_base=-0.05,
        mdd_variante=-0.04,
    )


def test_el_empate_estadistico_deja_la_capa_apagada():
    empate = bootstrap_pareado([0.4, -0.3, 0.2, -0.5, 0.6, -0.4], seed=1)
    assert not empate.significativo

    comp = comparacion(delta=empate, n_base=30, n_variante=30, ror_base=0.3, ror_variante=0.4)

    assert "APAGADA" in comp.veredicto()


def test_una_mejora_con_menos_trades_y_peor_retorno_sobre_riesgo_no_es_mejora():
    claro = bootstrap_pareado([0.3] * 20, seed=1)
    assert claro.significativo

    comp = comparacion(delta=claro, n_base=30, n_variante=18, ror_base=0.35, ror_variante=0.22)
    veredicto = comp.veredicto()

    assert "NO es una mejora" in veredicto
    assert "12 trades menos" in veredicto
    assert "0.350 -> 0.220" in veredicto


def test_una_mejora_con_menos_trades_pero_mejor_retorno_sobre_riesgo_si_cuenta():
    claro = bootstrap_pareado([0.3] * 20, seed=1)
    comp = comparacion(delta=claro, n_base=30, n_variante=18, ror_base=0.35, ror_variante=0.51)
    assert "mejora medible" in comp.veredicto()


def test_una_capa_que_empeora_queda_apagada():
    peor = bootstrap_pareado([-0.3] * 20, seed=1)
    comp = comparacion(delta=peor, n_base=30, n_variante=30, ror_base=0.35, ror_variante=0.2)
    assert "EMPEORA" in comp.veredicto()
