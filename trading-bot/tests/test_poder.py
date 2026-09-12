"""El cálculo de poder: la aritmética, y que cada capa mire los trades que le tocan.

Lo que se prueba acá no es "el número da lindo" sino que las relaciones sean las
correctas, porque de este número depende decidir si una capa se puede medir o si
medirla es perder el tiempo:

* el MDE por trade afectado escala con 1/√(f·n) y el global con √(f/n);
* la cantidad de trades necesarios es el inverso exacto del MDE;
* cada capa alcanza los trades que su regla alcanza, ni uno más;
* con pocos trades afectados el veredicto es "no medible" aunque el MDE dé holgado.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tradingbot.backtest.poder import (
    ALPHA,
    MIN_AFECTADOS,
    POTENCIA,
    curva_de_poder,
    factor_z,
    mde,
    poder_lineas,
    poder_por_capa,
    recorrido_medio,
    regimen_bajista,
    sigma_a_priori,
    trades_necesarios,
)
from tradingbot.backtest.portfolio import Trade

INICIO = date(2020, 1, 2)


def trade(*, pnl_r=0.0, mfe_r=0.0, mae_r=-1.0, bars=10, dia=0) -> Trade:
    return Trade(
        symbol="TEST",
        entry_date=INICIO + timedelta(days=dia),
        entry_price=100.0,
        shares=10,
        risk_per_share=10.0,
        stop_initial=90.0,
        exit_date=INICIO + timedelta(days=dia + bars),
        exit_price=100.0 + pnl_r * 10,
        exit_reasons=["hard_stop"],
        pnl=pnl_r * 100.0,
        pnl_r=pnl_r,
        bars_held=bars,
        mae_r=mae_r,
        mfe_r=mfe_r,
        commission=0.0,
        slippage=0.0,
    )


# --- la aritmética --------------------------------------------------------
def test_el_factor_z_es_el_de_5_por_ciento_y_80_de_potencia():
    assert (ALPHA, POTENCIA) == (0.05, 0.80)
    assert factor_z() == pytest.approx(1.959964 + 0.841621, abs=1e-5)


def test_el_mde_baja_con_la_raiz_de_n():
    chico = mde(1.4, 30)
    grande = mde(1.4, 120)
    assert grande.por_afectado == pytest.approx(chico.por_afectado / 2, rel=1e-9)


def test_una_capa_que_toca_menos_trades_necesita_un_efecto_mas_grande():
    todos = mde(1.4, 100, fraccion=1.0)
    raro = mde(1.4, 100, fraccion=0.15)

    # por trade afectado: 1/raíz(f) = 2.58 veces más exigente
    assert raro.por_afectado == pytest.approx(todos.por_afectado / np.sqrt(0.15))
    assert raro.por_afectado / todos.por_afectado == pytest.approx(2.58, abs=0.01)
    # sobre la expectancy global, en cambio, el efecto de una capa rara es chico
    assert raro.sobre_expectancy == pytest.approx(todos.sobre_expectancy * np.sqrt(0.15))


def test_la_relacion_entre_los_dos_mde_es_la_fraccion():
    valor = mde(1.4, 50, fraccion=0.4)
    assert valor.sobre_expectancy == pytest.approx(valor.por_afectado * 0.4)


def test_sin_trades_o_sin_fraccion_el_mde_es_infinito():
    assert mde(1.4, 0).por_afectado == float("inf")
    assert mde(1.4, 30, fraccion=0.0).por_afectado == float("inf")


def test_los_trades_necesarios_son_el_inverso_del_mde():
    n = trades_necesarios(0.30, sigma=1.4, fraccion=1.0)
    assert mde(1.4, n).por_afectado <= 0.30
    assert mde(1.4, n - 1).por_afectado > 0.30


def test_la_curva_es_monotona_en_la_fraccion():
    trades = [trade(pnl_r=0.5, mfe_r=1.5, mae_r=-0.5) for _ in range(40)]
    curva = curva_de_poder(trades)
    por_afectado = [valor.por_afectado for _, valor in curva]
    assert por_afectado == sorted(por_afectado)  # fracciones de mayor a menor


def test_sigma_a_priori_sale_del_recorrido_del_trade():
    trades = [trade(mfe_r=2.0, mae_r=-1.0) for _ in range(5)]
    assert recorrido_medio(trades) == pytest.approx(3.0)
    assert sigma_a_priori(trades) == pytest.approx(0.58 * 3.0)


# --- qué trades alcanza cada capa ----------------------------------------
def universo_de_prueba() -> list[Trade]:
    """Trades escritos para que cada capa alcance un subconjunto conocido."""
    return [
        # llegó a +2R y terminó perdiendo: break_even, trailing y giveback lo tocan
        *[trade(pnl_r=-1.0, mfe_r=2.0, bars=10, dia=i) for i in range(12)],
        # llegó a +0.5R y perdió: no arma ninguna capa de +1R
        *[trade(pnl_r=-1.0, mfe_r=0.5, bars=10, dia=20 + i) for i in range(8)],
        # ganador limpio de 3R, largo: trailing y time_stop lo tocan
        *[trade(pnl_r=3.0, mfe_r=3.0, bars=30, dia=40 + i) for i in range(10)],
    ]


def fila(nombre, filas):
    return next(f for f in filas if f.capa == nombre)


def test_cada_capa_alcanza_los_trades_de_su_regla():
    filas = poder_por_capa(universo_de_prueba())

    # trailing: todo trade que llegó a +1R -> 12 perdedores + 10 ganadores
    assert fila("trailing_stop", filas).n_afectados == 22
    # break_even: llegó a +1R y terminó perdiendo -> los 12
    assert fila("break_even", filas).n_afectados == 12
    # giveback: pasó de +1.5R y devolvió más del 40% -> los 12 (el ganador no devolvió nada)
    assert fila("giveback", filas).n_afectados == 12
    # time_stop: más de 20 velas -> los 10 ganadores largos
    assert fila("time_stop", filas).n_afectados == 10


def test_la_fraccion_es_afectados_sobre_el_total():
    filas = poder_por_capa(universo_de_prueba())
    assert fila("trailing_stop", filas).fraccion == pytest.approx(22 / 30)


def test_el_efecto_disponible_es_lo_que_la_capa_podria_llegar_a_cambiar():
    filas = poder_por_capa(universo_de_prueba())

    # break_even sobre un trade que fue a +2R y cerró en -1R: salva 1R
    assert fila("break_even", filas).efecto_disponible == pytest.approx(1.0)
    # trailing sobre esos mismos: del pico 2R al cierre -1R hay 3R sobre la mesa;
    # sobre los ganadores de 3R que cerraron en su pico no hay nada
    assert fila("trailing_stop", filas).efecto_disponible == pytest.approx(
        (12 * 3.0 + 10 * 0.0) / 22
    )


def test_pocos_trades_afectados_es_no_medible_aunque_el_mde_de_holgado():
    # tres trades con muchísimo en juego, entre sesenta de recorrido diminuto: el σ
    # del conjunto queda chico y el MDE da holgado, pero tres no son una medición
    trades = [trade(pnl_r=-1.0, mfe_r=5.0, mae_r=-1.0, bars=5, dia=i) for i in range(3)]
    trades += [
        trade(pnl_r=0.05, mfe_r=0.1, mae_r=-0.05, bars=5, dia=50 + i) for i in range(60)
    ]

    resultado = fila("break_even", poder_por_capa(trades))

    assert resultado.n_afectados == 3 < MIN_AFECTADOS
    assert resultado.efecto_disponible > resultado.mde_afectado  # habría margen
    assert not resultado.medible
    assert "3 trades afectados" in resultado.veredicto


def test_el_veredicto_dice_que_fraccion_del_efecto_hay_que_capturar():
    filas = poder_por_capa(universo_de_prueba())
    trailing = fila("trailing_stop", filas)

    assert trailing.exigencia == pytest.approx(
        trailing.mde_afectado / trailing.efecto_disponible
    )
    assert f"{trailing.exigencia:.0%}" in trailing.veredicto


def test_una_capa_sin_margen_lo_dice_sin_rodeos():
    # trades que no dejan nada sobre la mesa: cierran exactamente en su pico
    trades = [trade(pnl_r=1.05, mfe_r=1.05, mae_r=-0.2, bars=5, dia=i) for i in range(40)]
    trailing = fila("trailing_stop", poder_por_capa(trades))

    assert trailing.n_afectados == 40
    assert trailing.efecto_disponible == pytest.approx(0.0)
    assert "ni capturando todo" in trailing.veredicto


# --- el régimen de mercado, que sí se puede estimar exacto ----------------
def spy_frame(n: int = 400) -> pd.DataFrame:
    """SPY que sube 300 velas y después cae: la SMA200 se cruza una sola vez."""
    subida = np.linspace(100.0, 200.0, 300)
    bajada = np.linspace(200.0, 120.0, n - 300)
    close = np.concatenate([subida, bajada])
    index = pd.bdate_range("2019-01-01", periods=n, name="date")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1_000_000, dtype="int64"),
        },
        index=index,
    )


def test_el_regimen_se_evalua_con_la_vela_anterior_a_la_entrada():
    spy = spy_frame()
    bajista = regimen_bajista(spy)
    fechas_bajistas = bajista[bajista].index
    assert len(fechas_bajistas) > 10

    # un trade que entra el día siguiente a una vela bajista está alcanzado
    dentro = fechas_bajistas[5]
    siguiente = spy.index[spy.index.get_loc(dentro) + 1]
    alcanzado = Trade(
        symbol="TEST",
        entry_date=siguiente.date(),
        entry_price=100.0,
        shares=10,
        risk_per_share=10.0,
        stop_initial=90.0,
        exit_date=(siguiente + pd.Timedelta(days=5)).date(),
        exit_price=90.0,
        exit_reasons=["hard_stop"],
        pnl=-100.0,
        pnl_r=-1.0,
        bars_held=5,
        mae_r=-1.0,
        mfe_r=0.2,
        commission=0.0,
        slippage=0.0,
    )
    # y uno que entra al principio de la serie, en plena subida, no
    afuera = trade(pnl_r=1.0, mfe_r=1.0, dia=0)
    object.__setattr__(afuera, "entry_date", spy.index[250].date())

    filas = poder_por_capa([alcanzado, afuera], spy=spy)
    regimen = fila("market_regime", filas)

    assert regimen.n_afectados == 1
    assert regimen.cota == "exacta"
    assert regimen.efecto_disponible == pytest.approx(1.0)  # se ahorra la pérdida de 1R


def test_sin_spy_no_aparece_la_fila_del_regimen():
    nombres = [f.capa for f in poder_por_capa(universo_de_prueba())]
    assert "market_regime" not in nombres


# --- el bloque publicado --------------------------------------------------
def test_el_bloque_publica_la_curva_y_la_tabla_por_capa():
    lineas = "\n".join(poder_lineas(universo_de_prueba(), spy=spy_frame()))

    assert "PODER DE MEDICIÓN" in lineas
    assert "100%" in lineas and "15%" in lineas          # la curva por fracción
    for capa in ("trailing_stop", "break_even", "giveback", "time_stop", "market_regime"):
        assert capa in lineas
    # las dos que no se pueden estimar tienen que estar, con su motivo
    assert "reversal" in lineas and "no estimable sin la capa" in lineas
    assert "event_risk" in lineas and "sin red" in lineas


def test_sin_trades_el_bloque_lo_dice_en_vez_de_dividir_por_cero():
    assert "no hay nada que medir" in "\n".join(poder_lineas([]))
