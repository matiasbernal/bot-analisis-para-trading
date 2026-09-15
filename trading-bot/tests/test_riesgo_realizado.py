"""Cuánto riesgo tiene de verdad cada trade, comparado con el 1R que pide el YAML.

Medido sobre la plantilla ema_cross y el fixture sintético (31 posiciones
abiertas), con ``scripts/riesgo_realizado.py``:

    min 0.884   media 0.990   mediana 0.994   p95 0.999   max 1.000

Ninguna por encima de 1.00R: el motor arriesga menos de lo declarado, nunca más.
Lo que queda de desvío es el **redondeo a acciones enteras** más dos trades que
atan el tope de concentración.

**Con ``initial_cash: 100000`` (PLAN.md, "Cash real: antes de medir nada") el
riesgo se pega mucho más a 1.00R que antes**: con $10.000 la media daba 0.948 y
el mínimo 0.828, porque comprar 3 a 13 acciones por posición dejaba mucho margen
de redondeo; con diez veces más cash las posiciones son de cientos de acciones y
el redondeo a entero pesa una fracción mucho más chica del riesgo declarado.

**Antes del bloque 2 estos números eran otros**: con ``max_position_pct: 20`` la
media era 0.778 y el mínimo 0.539, porque el tope ataba 21 de los 31 trades. El
umbral es aritmético: el tope decide el tamaño cuando la distancia al stop, en %
del precio, es menor que ``risk_pct / max_position_pct``. Con 1.0/20 eso es 5% y
un stop de 2×ATR está a ~4.4%; con 1.0/30 el umbral baja a 3.33% y el riesgo
vuelve a decidirlo ``risk_pct``.

El gap **no** desvía el riesgo por acción: el stop se ancla al precio de fill
real, así que la distancia entrada-stop es exactamente 1R siempre.

**Por qué la plantilla es ``ema_cross_sin_trailing.yaml`` y no ``ema_cross.yaml``.**
Todo lo que se mide acá es del lado de la ENTRADA: cuántas acciones se compran y
cuánto riesgo real queda puesto. Con una capa de salida prendida ese número deja
de depender solo del sizing: el trailing cierra posiciones antes, eso cambia el
cash y la equity, y con otra equity el sizing de la señal siguiente da otra cosa.
La distribución medida pasaría a ser "sizing + trailing" y no diría nada sobre el
umbral ``risk_pct / max_position_pct``, que es lo que estos números sostienen.
Las dos plantillas comparten toda la calibración de entrada y difieren solo en el
trailing; ``test_trailing_chandelier.py`` verifica que no se separen.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest
import yaml

from tradingbot.backtest.engine import run_backtest
from tradingbot.config import StrategyConfig, load_strategy

PLANTILLA = "config/strategies/ema_cross_sin_trailing.yaml"


def _medir(config, frames) -> pd.DataFrame:
    """Riesgo realizado de cada trade, en unidades del riesgo objetivo."""
    result = run_backtest(config, frames)
    risk_pct = config.risk.position_sizing.risk_pct / 100.0
    filas = []
    for trade in result.trades:
        index = frames[trade.symbol].index
        i = index.get_loc(pd.Timestamp(trade.entry_date))
        objetivo = float(result.equity.loc[index[i - 1]]) * risk_pct
        filas.append(
            {
                "trade": trade,
                "objetivo": objetivo,
                "r": trade.risk_amount / objetivo,
                "stop_pct": trade.risk_per_share / trade.entry_price * 100,
            }
        )
    return result, pd.DataFrame(filas)


@pytest.fixture(scope="module")
def medicion(universe_frames_module):
    return _medir(load_strategy(PLANTILLA), universe_frames_module)


@pytest.fixture(scope="module")
def universe_frames_module():
    from fixtures.synthetic import synthetic_universe

    from tradingbot.data.validate import validate_ohlcv

    return {s: validate_ohlcv(df, s) for s, df in synthetic_universe().items()}


def test_el_riesgo_inicial_nunca_supera_el_objetivo(medicion):
    """La única cota que importa: el motor no puede arriesgar más de lo declarado."""
    _, tabla = medicion
    assert len(tabla) == 31
    assert tabla["r"].max() <= 1.0
    assert (tabla["r"] > 1.0).sum() == 0


def test_la_distribucion_medida_no_se_mueve_sin_que_nos_enteremos(medicion):
    """Fija los números del docstring: si el sizing cambia, este test lo dice."""
    _, tabla = medicion
    r = tabla["r"]
    assert r.min() == pytest.approx(0.884, abs=0.005)
    assert r.mean() == pytest.approx(0.990, abs=0.005)
    assert r.max() == pytest.approx(1.000, abs=0.005)
    assert r.std(ddof=1) == pytest.approx(0.020, abs=0.005)


def test_el_stop_esta_exactamente_a_1r_del_fill(medicion):
    """El gap de la apertura no desvía el riesgo: el stop se ancla al fill real."""
    result, _ = medicion
    for trade in result.trades:
        assert trade.entry_price - trade.stop_initial == pytest.approx(
            trade.risk_per_share, abs=1e-9
        )
        assert trade.risk_amount == pytest.approx(trade.shares * trade.risk_per_share)


def test_con_el_tope_en_30_el_riesgo_vuelve_a_decidirlo_risk_pct(medicion):
    """Con la plantilla actual, el tope ata un trade de 31, no 21."""
    result, tabla = medicion
    atados = sum(
        1
        for fila in tabla.itertuples()
        if fila.trade.shares < math.floor(fila.objetivo / fila.trade.risk_per_share)
    )
    assert result.config.risk.max_position_pct == 30.0
    assert atados <= 2
    assert result.metrics["sizing_by_cap"] <= 2
    assert result.metrics["sizing_by_risk"] >= 29


def test_el_sesgo_por_atr_aparece_cuando_el_tope_ata(universe_frames_module):
    """El tope castiga a los trades tranquilos: stop cerca -> posición recortada.

    Es el sesgo de asignación que ninguna de las opciones evaluadas arregla: el
    tope ata cuando el stop está cerca, y el stop está cerca cuando el ATR es
    bajo, así que el motor arriesga menos en los trades tranquilos y 1R completo
    en los volátiles — al revés de lo deseable.

    Está **dormido** mientras risk_pct decide el tamaño (tope 30%) y **vuelve**
    apenas el tope ata (tope 20%). Este test fija las dos mediciones.

    **Con ``initial_cash: 100000`` el coeficiente de correlación del tope 30 subió
    de 0.06 a 0.39** aunque el sesgo en R casi no se movió (0.002R -> 0.014R): es
    la regla del cociente inestable (``tradingbot/backtest/cocientes.py``) actuando
    sobre una correlación. Con más cash el redondeo a acciones enteras pesa mucho
    menos (std de `r` bajó de 0.038 a 0.020, ver el test de la distribución), así
    que el poco ruido que queda —dos trades atados por el tope en vez de uno— se ve
    más grande en una estadística normalizada por ese desvío más chico. El efecto
    en R, que es lo que importa para la plata, sigue siendo chico frente al sesgo
    despierto del tope 20 (0.30R). Por eso el test mira las dos cosas y no solo la
    correlación.
    """
    datos = yaml.safe_load(open(PLANTILLA, encoding="utf-8"))

    datos["risk"]["max_position_pct"] = 30
    _, con_30 = _medir(StrategyConfig(**datos), universe_frames_module)
    datos["risk"]["max_position_pct"] = 20
    _, con_20 = _medir(StrategyConfig(**datos), universe_frames_module)

    corr_20 = con_20["r"].corr(con_20["stop_pct"])
    corr_30 = con_30["r"].corr(con_30["stop_pct"])
    # con el tope atando, el riesgo realizado sigue a la distancia del stop
    assert corr_20 > 0.8
    # con el tope suelto la relación se debilita mucho, aunque ya no cae bajo 0.3
    # como con $10.000 (ver docstring: la correlación es un cociente y hereda la
    # inestabilidad de un desvío más chico)
    assert corr_30 < corr_20 * 0.5

    def tercios(tabla):
        bajo, alto = tabla["stop_pct"].quantile([0.33, 0.67])
        return (
            tabla[tabla["stop_pct"] <= bajo]["r"].mean(),
            tabla[tabla["stop_pct"] >= alto]["r"].mean(),
        )

    cerca_20, lejos_20 = tercios(con_20)
    cerca_30, lejos_30 = tercios(con_30)
    assert lejos_20 - cerca_20 == pytest.approx(0.302, abs=0.02)  # sesgo fuerte
    assert lejos_30 - cerca_30 == pytest.approx(0.014, abs=0.02)  # sesgo dormido, en R


def test_el_motor_avisa_cuando_risk_pct_queda_decorativo(universe_frames_module):
    datos = yaml.safe_load(open(PLANTILLA, encoding="utf-8"))
    datos["risk"]["max_position_pct"] = 20
    result = run_backtest(StrategyConfig(**datos), universe_frames_module)

    assert result.sizing_warnings, "el aviso no apareció con el tope que lo provoca"
    assert "decorativo" in result.sizing_warnings[0]
    assert "5.00%" in result.sizing_warnings[0]  # risk_pct/max_position_pct

    con_30 = run_backtest(load_strategy(PLANTILLA), universe_frames_module)
    assert not con_30.sizing_warnings


def test_el_umbral_es_el_cociente_de_los_dos_parametros():
    config = load_strategy(PLANTILLA)
    assert config.sizing_threshold_pct == pytest.approx(1.0 / 30 * 100)
    assert config.static_warnings() == []  # stop en ATR: el aviso lo da el motor


# --- el régimen que motivó todo esto, ejercitado -----------------------------
@pytest.fixture(scope="module")
def con_tope_20(universe_frames_module):
    """La plantilla con el tope viejo: el estado en el que el aviso gritaba."""
    datos = yaml.safe_load(open(PLANTILLA, encoding="utf-8"))
    datos["risk"]["max_position_pct"] = 20
    return run_backtest(StrategyConfig(**datos), universe_frames_module)


def test_con_tope_20_el_aviso_aparece_completo(con_tope_20):
    """Sin esto, nada del repo ejercita el aviso en el régimen que lo motivó."""
    assert len(con_tope_20.sizing_warnings) == 1
    aviso = con_tope_20.sizing_warnings[0]
    assert "decorativo" in aviso
    assert "5.00%" in aviso                      # risk_pct/max_position_pct
    assert "4.55%" in aviso                      # distancia mediana al stop
    assert "max_position_pct" in aviso and "risk_pct" in aviso


def test_con_tope_20_el_contador_dice_22_de_31(con_tope_20):
    """Con ``initial_cash: 100000`` el tope ata 22 de 31, no 21.

    Antes, con $10.000, era 21. La diferencia de un trade viene del mismo
    redondeo a acciones enteras que documenta el test de la distribución: con
    diez veces más cash el umbral ``risk_pct/max_position_pct`` no se mueve
    (es un cociente de porcentajes, no depende de la plata), pero el punto
    exacto donde el piso entero de ``by_risk`` y ``by_concentration`` empatan sí
    puede cambiar de lado en algún trade puntual.
    """
    m = con_tope_20.metrics
    assert (m["sizing_by_risk"], m["sizing_by_cap"], m["sizing_by_cash"]) == (9, 22, 0)
    assert m["sizing_by_cap"] + m["sizing_by_cash"] == 22
    assert sum(m[k] for k in ("sizing_by_risk", "sizing_by_cap", "sizing_by_cash")) == 31


def test_con_tope_20_la_lectura_ingenua_se_equivoca_46_por_ciento(con_tope_20):
    """El número que justificó separar la unidad declarada de la realizada.

    Con ``initial_cash: 100000`` todo escala ×10 en pesos (el % declarado no
    cambia), y el error relativo se mantiene en el mismo orden:

    expectancy +0.251189R × $998.29 declarados = $250.76 por trade
    promedio real                                = $172.21 por trade
    error = |250.76 / 172.21 − 1| = 45.6%
    """
    metricas = con_tope_20.metrics
    trades = con_tope_20.rule_trades
    declarado = sum(t.risk_target for t in trades) / len(trades)

    assert declarado == pytest.approx(998.29, abs=0.5)
    assert metricas["expectancy_money"] == pytest.approx(172.21, abs=0.5)
    ingenua = metricas["expectancy_r"] * declarado
    assert ingenua == pytest.approx(250.76, abs=0.5)
    assert abs(ingenua / metricas["expectancy_money"] - 1) * 100 == pytest.approx(
        45.6, abs=1.0
    )


def test_con_tope_20_el_informe_imprime_las_dos_cosas(con_tope_20):
    from tradingbot.reporting.report import risk_unit_lines

    texto = "\n".join(risk_unit_lines(con_tope_20))
    assert "risk_pct NO decidió el tamaño en 22 de 31 señales" in texto
    assert "AVISO:" in texto and "decorativo" in texto
    assert "Esa lectura se equivoca 46%" in texto


def test_con_la_plantilla_actual_nada_de_eso_aparece(medicion):
    """El contraste: con tope 30 el aviso se calla y el error cae a un dígito."""
    result, _ = medicion
    from tradingbot.reporting.report import risk_unit_lines

    texto = "\n".join(risk_unit_lines(result))
    assert not result.sizing_warnings
    assert "AVISO:" not in texto
    assert result.metrics["sizing_by_cap"] <= 2

    trades = result.rule_trades
    declarado = sum(t.risk_target for t in trades) / len(trades)
    ingenua = result.metrics["expectancy_r"] * declarado
    error = abs(ingenua / result.metrics["expectancy_money"] - 1) * 100
    assert error < 10


def test_con_la_expectancy_cerca_de_cero_no_se_publica_un_error_porcentual(
    universe_frames_module,
):
    """Un cociente sobre ruido no es un número: se publica la diferencia en pesos.

    Con el trailing prendido la expectancy en plata de este fixture queda en
    $+30.00 (era $+0.67 con ``initial_cash: 10000``: todo escala con el cash, la
    expectancy en plata incluida). Sigue por debajo del piso
    (``PISO_PESOS_SOBRE_R`` = 5% del 1R realizado medio, que acá es $972 ->
    piso ~$48.6), así que el cociente sigue sin publicarse por el mismo motivo
    de siempre: el denominador es ruido, no una medición.
    """
    from tradingbot.backtest.cocientes import PISO_PESOS_SOBRE_R
    from tradingbot.reporting.report import risk_unit_lines

    config = load_strategy("config/strategies/ema_cross.yaml")  # v4, con trailing
    result = run_backtest(config, universe_frames_module)
    texto = "\n".join(risk_unit_lines(result))

    trades = result.rule_trades
    riesgo_realizado_medio = sum(t.risk_amount for t in trades) / len(trades)
    piso = PISO_PESOS_SOBRE_R * riesgo_realizado_medio
    assert abs(result.metrics["expectancy_money"]) < piso, (
        "la expectancy en plata superó el piso: el test perdió su caso de "
        "'cociente sobre ruido'"
    )
    assert "La diferencia es de $" in texto
    assert "cociente sobre ruido" in texto
    assert "se equivoca" not in texto
