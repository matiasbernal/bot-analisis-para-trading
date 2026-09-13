"""Riesgo de cartera (tanda 2B): los cinco controles, sobre datos que los ejercitan.

**Estos controles son restricciones, no candidatos del torneo.** No se miden con
el banco A/B ni se les calcula poder: se cumplen o no se cumplen, y eso se
verifica. Por eso 2B avanzó sin esperar CSV reales, mientras 2C sigue parada.

El universo de estos tests es el **correlacionado** y no el de la tanda 1, y la
diferencia no es cosmética: sobre series independientes la volatilidad de la
cartera es el 32% de la de sus componentes contra 78% en el correlacionado, así
que cualquier control de riesgo de cartera probado sobre las primeras se vería
mucho mejor de lo que es. Para los cortacircuitos van velas a mano, porque hace
falta una caída de tamaño exacto y en un mes concreto del calendario.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest
from conftest import make_strategy
from fixtures.candles import flat, frame

sys.path.insert(0, str(Path(__file__).parent))
from fixtures.synthetic import GRUPOS, correlated_universe, grupo_de  # noqa: E402

from tradingbot.backtest.engine import run_backtest  # noqa: E402
from tradingbot.data.validate import validate_ohlcv  # noqa: E402
from tradingbot.reporting.report import rejection_table, render_console  # noqa: E402
from tradingbot.strategy import portfolio_risk  # noqa: E402
from tradingbot.strategy.portfolio_risk import (  # noqa: E402
    Comprometido,
    GroupLabelError,
    GuardiaDeCartera,
    heat_en_pesos,
    riesgo_de,
)
from tradingbot.strategy.position import Position  # noqa: E402

TOPE_HEAT = 4.0
TOPE_GRUPO = 2


def etiquetas(symbols) -> dict[str, dict[str, str]]:
    """``{símbolo: {sector: grupo}}``, que es lo que universe.yaml daría."""
    return {s: {"sector": grupo_de(s)} for s in symbols}


def posicion(symbol="TEST", *, shares=10, entry=100.0, stop=95.0) -> Position:
    return Position(
        symbol=symbol,
        entry_date=None,
        entry_price=entry,
        shares=shares,
        risk_per_share=entry - stop,
        stop_current=stop,
        peak_price=entry,
    )


# --- 3.2 el heat va en pesos ------------------------------------------------
def test_el_heat_es_acciones_por_distancia_al_stop_y_no_r_nominales():
    """10 acciones con el stop 5 puntos abajo son $50 de riesgo, no "1R"."""
    p = posicion(shares=10, entry=100.0, stop=95.0)
    assert riesgo_de(p) == pytest.approx(50.0)
    assert heat_en_pesos([p, posicion("OTRO", shares=4, entry=50.0, stop=48.0)]) == (
        pytest.approx(58.0)
    )


def test_una_posicion_con_el_stop_arriba_de_la_entrada_aporta_cero_y_no_negativo():
    """El trailing ya aseguró ganancia: esa posición no arriesga, pero no cancela.

    ``risk_at_stake`` se vuelve negativo cuando el stop pasó arriba de la entrada,
    y eso es correcto como número de la posición. Lo que no puede hacer es restar
    del heat de la cartera: dos trades cubiertos no "pagan" la apertura de un
    tercero expuesto, y sumar con signo dejaría exactamente eso.
    """
    cubierta = posicion(shares=10, entry=100.0, stop=95.0)
    cubierta.raise_stop(108.0, source="trailing_stop")

    assert cubierta.risk_at_stake(cubierta.entry_price) < 0
    assert riesgo_de(cubierta) == 0.0

    expuesta = posicion("OTRO", shares=10, entry=100.0, stop=95.0)
    assert heat_en_pesos([cubierta, expuesta]) == pytest.approx(50.0)


def test_la_sexta_senal_con_el_heat_en_4r_se_rechaza():
    """Cinco posiciones de 0.8% cada una llenan el 4%: la sexta no entra.

    El número que decide es la plata, no la cuenta de posiciones: cinco de 0.8%
    dan 4.00% y frenan, mientras que cinco de 0.5% darían 2.5% y dejarían pasar
    varias más. Contando "cinco posiciones de 1R" las dos carteras se verían
    iguales, y no lo son.
    """
    guardia = GuardiaDeCartera(max_portfolio_heat_r=TOPE_HEAT)
    equity = 10_000.0
    abiertas = [Comprometido(f"S{i}", 80.0) for i in range(5)]  # 5 x 0.8% = 4.00%

    assert guardia.rechazo_por_heat(80.0, abiertas, equity) is not None
    motivo = guardia.rechazo_por_heat(80.0, abiertas, equity)
    assert motivo.startswith(portfolio_risk.MOTIVO_HEAT)
    assert "4.80%" in motivo and "4.00%" in motivo

    # justo en el tope entra: la comparación es estricta, no "casi"
    cuatro = [Comprometido(f"S{i}", 80.0) for i in range(4)]
    assert guardia.rechazo_por_heat(80.0, cuatro, equity) is None


def test_las_ordenes_pendientes_cuentan_en_el_heat():
    """Si no contaran, cinco señales de la misma noche pasarían las cinco."""
    guardia = GuardiaDeCartera(max_portfolio_heat_r=TOPE_HEAT)
    solo_abiertas = [Comprometido("A", 300.0)]
    con_pendiente = solo_abiertas + [Comprometido("B", 200.0)]

    assert guardia.rechazo_por_heat(100.0, solo_abiertas, 10_000.0) is None
    assert guardia.rechazo_por_heat(100.0, con_pendiente, 10_000.0) is not None


# --- 3.4 sobre el universo correlacionado -----------------------------------
@pytest.fixture(scope="module")
def universo():
    return {s: validate_ohlcv(df, s) for s, df in correlated_universe().items()}


def estrategia(**risk):
    base = {
        "position_sizing": {"risk_pct": 1.0},
        "max_position_pct": 30.0,
        "max_open_positions": 10,  # alto a propósito: se quiere ver atar a los otros
    }
    base.update(risk)
    return make_strategy(
        universe=sorted(GRUPOS_PLANOS),
        warmup_bars=200,
        indicators={
            "ema_fast": {"type": "ema", "period": 20},
            "ema_slow": {"type": "ema", "period": 50},
            "atr": {"type": "atr", "period": 14},
        },
        entry={"all": [{"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}]},
        exits={
            "signal": {"any": [{"left": "ema_fast", "op": "crosses_below", "right": "ema_slow"}]},
            "hard_stop": {"mode": "atr", "multiple": 2.0},
            "take_profit": {"ratio": 3.0},
        },
        risk=base,
    )


GRUPOS_PLANOS = [s for symbols in GRUPOS.values() for s in symbols]


def abiertas_al_cierre(result) -> dict[pd.Timestamp, list]:
    """Qué posiciones estaban abiertas al cierre de cada vela, desde los trades.

    El intervalo es ``[entrada, salida)`` y no cerrado: una posición que se cerró
    en la APERTURA del día D ya no está al cierre de D. La excepción es el cierre
    forzado por fin de datos, que es el único fill del motor que ejecuta al
    cierre, así que ahí el último día sí cuenta.
    """
    por_dia: dict[pd.Timestamp, list] = {}
    for dia in result.equity.index:
        vivas = []
        for trade in result.trades:
            entrada, salida = pd.Timestamp(trade.entry_date), pd.Timestamp(trade.exit_date)
            if entrada <= dia < salida or (trade.is_forced_close and entrada <= dia <= salida):
                vivas.append(trade)
        por_dia[dia] = vivas
    return por_dia


def test_tres_senales_del_mismo_grupo_con_tope_2_dejan_una_afuera(universo):
    """El control se ejercita de verdad: el fixture produce el escenario.

    Sin el límite hay días con 3 y 4 posiciones abiertas del mismo sector (por eso
    el universo correlacionado tiene un grupo de 4 y otro de 3, y no dos por
    grupo: con dos, ``max_per_group: 2`` no se podría violar nunca). Con el
    límite puesto no queda ninguno, y los que se frenaron están registrados.
    """
    grupos = etiquetas(universo)
    sin_limite = run_backtest(estrategia(), universo, groups=grupos)
    con_limite = run_backtest(
        estrategia(max_per_group={"sector": TOPE_GRUPO}), universo, groups=grupos
    )

    def max_por_grupo(result) -> int:
        peor = 0
        for _, vivas in abiertas_al_cierre(result).items():
            cuenta = Counter(grupo_de(t.symbol) for t in vivas)
            peor = max(peor, max(cuenta.values(), default=0))
        return peor

    assert max_por_grupo(sin_limite) >= 3, (
        "el fixture no produjo 3 posiciones simultáneas del mismo grupo: el test "
        "no estaría probando el control"
    )
    assert max_por_grupo(con_limite) <= TOPE_GRUPO

    rechazos = [
        r for r in con_limite.rejections
        if r.reason.startswith(portfolio_risk.MOTIVO_GRUPO)
    ]
    assert rechazos, "el límite ató pero no registró ni un rechazo"
    assert "sector=" in rechazos[0].reason and f"el tope es {TOPE_GRUPO}" in rechazos[0].reason
    assert len(con_limite.trades) < len(sin_limite.trades)


def test_el_heat_ata_y_los_rechazos_quedan_registrados(universo):
    """Con el tope al 4% el heat máximo baja, y las señales frenadas se cuentan."""
    grupos = etiquetas(universo)
    sin_tope = run_backtest(estrategia(), universo, groups=grupos)
    con_tope = run_backtest(
        estrategia(max_portfolio_heat_r=TOPE_HEAT), universo, groups=grupos
    )

    assert sin_tope.portfolio_heat.max() * 100 > TOPE_HEAT, (
        "sin tope el heat nunca pasó del 4%: el control no tendría nada que hacer"
    )
    rechazos = [
        r for r in con_tope.rejections if r.reason.startswith(portfolio_risk.MOTIVO_HEAT)
    ]
    assert rechazos, "el heat no rechazó ninguna señal"
    assert con_tope.portfolio_heat.max() < sin_tope.portfolio_heat.max()

    # El control es EX ANTE: se aplica contra la equity del cierre de la señal. Si
    # después la equity cae, el mismo riesgo abierto pesa más y el heat realizado
    # puede quedar apenas arriba del tope sin que eso sea un incumplimiento.
    exceso = con_tope.portfolio_heat.max() * 100 - TOPE_HEAT
    assert exceso < 0.5, f"el heat se fue {exceso:.2f} puntos arriba del tope"


def test_el_heat_del_motor_es_el_que_sale_de_recalcularlo_a_mano(universo):
    """Contra una reconstrucción independiente, en todas las velas del período.

    La guardia recalcula el heat desde las posiciones vivas en cada consulta, sin
    contador incremental, justamente para que esto valga: un acumulador se
    desincroniza el día que varios stops saltan juntos y el error no se ve, porque
    el número sigue siendo plausible.
    """
    grupos = etiquetas(universo)
    result = run_backtest(
        estrategia(max_portfolio_heat_r=TOPE_HEAT), universo, groups=grupos
    )
    vivas_por_dia = abiertas_al_cierre(result)

    peor = 0.0
    for dia, vivas in vivas_por_dia.items():
        a_mano = sum(t.risk_amount for t in vivas) / float(result.equity.loc[dia])
        peor = max(peor, abs(a_mano - float(result.portfolio_heat.loc[dia])))
    assert peor < 1e-12, f"el heat del motor difiere del recalculado en {peor}"


def test_gaps_correlacionados_saltan_varios_stops_la_misma_manana(universo):
    """El escenario que el heat tiene que sobrevivir, con el heat verificado después.

    El fixture por defecto casi no produce gaps que lleguen al stop de 2×ATR, así
    que acá se usa una versión **estresada**: mismos símbolos, misma estructura de
    correlación (que es lo que hace que los huecos se abran juntos), gaps 16 veces
    más volátiles y stops de 0.75×ATR. No es una predicción de nada: es la mañana
    mala construida a propósito para ver si el control la aguanta.
    """
    frames = {
        s: validate_ohlcv(df, s)
        for s, df in correlated_universe(gap_volatility=0.05).items()
    }
    grupos = etiquetas(frames)
    config = estrategia(max_portfolio_heat_r=TOPE_HEAT)
    config.exits.hard_stop.multiple = 0.75
    result = run_backtest(config, frames, groups=grupos)

    por_manana: Counter = Counter()
    for trade in result.trades:
        if any("gap" in motivo for motivo in trade.exit_reasons):
            por_manana[pd.Timestamp(trade.exit_date)] += 1

    multiples = {dia: n for dia, n in por_manana.items() if n >= 2}
    assert len(multiples) >= 3, f"solo {len(multiples)} mañanas con 2+ stops por gap"
    assert max(por_manana.values()) >= 3, "nunca saltaron 3 stops la misma mañana"

    # y el heat después de cada una de esas mañanas es el que sale de recalcularlo
    vivas_por_dia = abiertas_al_cierre(result)
    for dia in sorted(multiples):
        a_mano = sum(t.risk_amount for t in vivas_por_dia[dia]) / float(
            result.equity.loc[dia]
        )
        assert a_mano == pytest.approx(float(result.portfolio_heat.loc[dia]), abs=1e-12)

    # el riesgo de las posiciones que saltaron dejó de contar: el heat baja
    peor_manana = max(por_manana, key=lambda d: por_manana[d])
    anterior = result.equity.index[result.equity.index < peor_manana][-1]
    assert result.portfolio_heat.loc[peor_manana] < result.portfolio_heat.loc[anterior]


def test_sin_etiqueta_el_limite_por_grupo_no_arranca(universo):
    """Un símbolo sin sector no se mete en un cajón "otros" en silencio."""
    grupos = etiquetas(universo)
    grupos.pop("NVDA")
    with pytest.raises(GroupLabelError, match="NVDA no tiene esa etiqueta"):
        run_backtest(
            estrategia(max_per_group={"sector": TOPE_GRUPO}), universo, groups=grupos
        )


# --- 3.4 y 3.5: los cortacircuitos, con velas a mano ------------------------
#: con risk_pct 5 y hard_stop pct 5 sobre un cierre de 100: 1R = 5 por acción y el
#: sizing pide 100 acciones, que el tope de concentración recorta a 50 ($5.000).
#: Cada punto que cae el papel son $50, o sea 0.5% del equity inicial.
CB_RISK = {
    "position_sizing": {"risk_pct": 5.0},
    "max_position_pct": 50.0,
    "max_open_positions": 5,
}


def _cb_run(bars_por_simbolo: dict[str, list], *, stop_pct: float = 5.0, **risk):
    frames = {
        s: validate_ohlcv(frame(bars), s) for s, bars in bars_por_simbolo.items()
    }
    config = make_strategy(
        universe=sorted(frames),
        warmup_bars=5,
        exits={
            "hard_stop": {"mode": "pct", "pct": stop_pct},
            "take_profit": {"mode": "rr", "ratio": 3.0},
        },
        risk={**CB_RISK, **risk},
    )
    return run_backtest(config, frames), frames


def _derrumbe(caida: float, dias_despues: int) -> list:
    """7 velas planas en 100, una que abre en ``100 − caida``, y el resto planas.

    Con 50 acciones, una caída de 16 puntos son $800: −8% del equity, que pasa el
    tope mensual del 6%. Las planas de después son los días en los que el
    cortacircuito tiene que seguir rechazando.
    """
    return (
        flat(7)
        + [(100.0 - caida, 100.0 - caida + 1, 100.0 - caida - 1, 100.0 - caida)]
        + flat(dias_despues, 100.0 - caida)
    )


def test_un_mes_a_menos_6_bloquea_entradas_hasta_el_mes_que_viene():
    """El mes malo se corta y el mes que viene se arranca de cero.

    Las velas empiezan el 2020-01-01 y son días hábiles, así que enero son las
    primeras 23 y febrero arranca en la 24. El derrumbe cae en enero: a partir de
    ahí y hasta fin de mes toda señal se rechaza con el motivo del cortacircuito,
    y en febrero se vuelve a abrir sin que nadie lo reactive a mano.
    """
    result, _ = _cb_run(
        {"TEST": _derrumbe(16.0, 33)},
        circuit_breaker={"monthly_drawdown_pct": 6.0},
    )

    frenadas = [
        r for r in result.rejections
        if r.reason.startswith(portfolio_risk.MOTIVO_CB_MES)
    ]
    assert frenadas, "el mes cayó 8% y el cortacircuito no frenó nada"
    assert all(r.date.month == 1 for r in frenadas), (
        "el bloqueo se filtró a febrero: el cortacircuito mensual se levanta solo"
    )
    assert "el mes va" in frenadas[0].reason and "tope es -6.00%" in frenadas[0].reason

    # y en febrero volvió a operar
    entradas_febrero = [t for t in result.trades if t.entry_date.month == 2]
    assert entradas_febrero, "febrero arrancó bloqueado: el latch no se soltó"


def test_el_bloqueo_mensual_no_se_levanta_porque_la_equity_repunte():
    """Es un latch dentro del mes, y a propósito.

    La regla es dejar de operar el mes malo, no operar en los repuntes del mes
    malo: si se soltara al primer rebote, el sistema volvería a entrar justo en el
    medio de la racha que motivó el corte.
    """
    guardia = GuardiaDeCartera(monthly_drawdown_pct=6.0)
    guardia.marcar(pd.Timestamp("2020-01-02"), 10_000.0)
    assert not guardia.frenado

    guardia.marcar(pd.Timestamp("2020-01-20"), 9_300.0)  # −7%
    assert guardia.mes_bloqueado

    guardia.marcar(pd.Timestamp("2020-01-28"), 9_950.0)  # repunta a −0.5%
    assert guardia.mes_bloqueado, "el repunte levantó el bloqueo del mes"

    guardia.marcar(pd.Timestamp("2020-02-03"), 9_950.0)  # mes nuevo
    assert not guardia.frenado


#: El cortacircuito del pico necesita una caída que NO toque el stop: si el papel
#: se derrumba de golpe, el hard stop cierra las posiciones intrabar y a la hora
#: de liquidar ya no queda nada, o sea que el test no probaría el control. Por eso
#: acá el stop va lejos (25%) y la caída es escalonada: −4 puntos por vela, con
#: los mínimos siempre arriba del stop.
DECLIVE_RISK = {
    "position_sizing": {"risk_pct": 20.0},
    "max_position_pct": 50.0,
    "max_open_positions": 5,
}


def _declive(pasos: int, salto: float, dias_despues: int) -> list:
    """7 velas planas en 100 y después ``pasos`` velas que bajan ``salto`` cada una."""
    bars = flat(7)
    precio = 100.0
    for _ in range(pasos):
        siguiente = precio - salto
        bars.append((precio, precio, siguiente, siguiente))
        precio = siguiente
    return bars + flat(dias_despues, precio)


def test_el_cortacircuito_del_pico_cierra_todo_y_no_vuelve_a_abrir():
    """3.5: a −15% del máximo se liquida y se para, sin reanudar solo.

    Dos símbolos para que "cierra todo" signifique algo: los dos tienen que
    aparecer con el motivo del cortacircuito, y después no puede haber ninguna
    entrada nueva en lo que queda del período, que son más de dos meses.

    Cada símbolo entra con 50 acciones a $100 (el tope de concentración recorta a
    la mitad del equity), así que los dos juntos ponen los $10.000. Cuatro velas
    de −4 puntos llevan el precio a 84 sin tocar el stop (que está en 75) y la
    equity a $8.400: −16% del máximo, o sea que el corte del 15% tiene que saltar.
    """
    result, frames = _cb_run(
        {"AAA": _declive(4, 4.0, 60), "BBB": _declive(4, 4.0, 60)},
        stop_pct=25.0,
        **DECLIVE_RISK,
        circuit_breaker={"peak_drawdown_pct": 15.0},
    )

    cerrados = [
        t for t in result.trades
        if portfolio_risk.RAZON_CIERRE_POR_PICO in t.exit_reasons
    ]
    assert {t.symbol for t in cerrados} == {"AAA", "BBB"}, (
        f"el cortacircuito no cerró las dos posiciones: {[t.symbol for t in cerrados]}"
    )

    corte = min(t.exit_date for t in cerrados)
    posteriores = [t for t in result.trades if t.entry_date > corte]
    assert not posteriores, f"se abrieron {len(posteriores)} posiciones después del corte"

    frenadas = [
        r for r in result.rejections
        if r.reason.startswith(portfolio_risk.MOTIVO_CB_PICO)
    ]
    assert frenadas, "no quedó registrado ni un rechazo por el cortacircuito del pico"
    assert "no se vuelve a abrir" in frenadas[0].reason
    # y el período seguía: el corte no fue el final de los datos
    assert result.equity.index[-1] > pd.Timestamp(corte) + pd.Timedelta(days=30)


def test_sin_cortacircuito_la_misma_caida_no_cierra_nada():
    """La contraprueba: sin el control, las posiciones siguen abiertas al final.

    Es lo que muestra que el test de arriba mide el cortacircuito y no el hard
    stop: con la misma caída y sin el control, nadie cierra nada.
    """
    result, _ = _cb_run(
        {"AAA": _declive(4, 4.0, 60), "BBB": _declive(4, 4.0, 60)},
        stop_pct=25.0,
        **DECLIVE_RISK,
    )
    assert not [
        t for t in result.trades
        if portfolio_risk.RAZON_CIERRE_POR_PICO in t.exit_reasons
    ]
    assert len(result.forced_closes) == 2, (
        "sin cortacircuito las dos posiciones tenían que llegar abiertas al final"
    )


# --- 3.3 la tabla de rechazos ----------------------------------------------
def test_el_informe_publica_la_tabla_de_rechazos_por_categoria(universo):
    """El PLAN pide que el backtest refleje las señales que se podrían haber tomado."""
    grupos = etiquetas(universo)
    result = run_backtest(
        estrategia(max_portfolio_heat_r=TOPE_HEAT, max_per_group={"sector": TOPE_GRUPO}),
        universo,
        groups=grupos,
    )
    tabla = rejection_table(result)
    categorias = {fila["categoria"]: fila["count"] for fila in tabla}

    assert "heat de cartera" in categorias
    assert "límite por grupo" in categorias
    # la suma cierra contra el total: ningún rechazo se pierde por el camino
    assert sum(categorias.values()) == len(result.rejections)

    texto = render_console(result)
    assert "Señales rechazadas" in texto
    assert "heat de cartera" in texto and "límite por grupo" in texto
    assert "Heat de cartera (Σ riesgo real abierto / equity)" in texto


def test_la_plantilla_de_cartera_corre_de_punta_a_punta_por_cli(tmp_path):
    """La plantilla lee las etiquetas de universe.yaml y publica la tabla.

    Es el único test que ejercita el camino completo —YAML de estrategia +
    universe.yaml + CLI—, que es donde se rompería un cambio de nombre de
    etiqueta sin que ningún test unitario se entere.
    """
    import subprocess

    raiz = Path(__file__).resolve().parents[1]
    proceso = subprocess.run(
        [
            sys.executable, "-m", "tradingbot.cli", "backtest",
            "--strategy", str(raiz / "config/strategies/cartera_correlacionada.yaml"),
            "--data", str(raiz / "tests/fixtures/correlated"),
        ],
        capture_output=True, text=True, cwd=raiz,
    )
    assert proceso.returncode == 0, proceso.stderr
    salida = proceso.stdout

    assert "Señales rechazadas" in salida
    assert "límite por grupo" in salida
    assert "sector=technology" in salida or "sector=energy" in salida
    assert "Heat de cartera" in salida
    assert "tope (max_portfolio_heat_r)" in salida


def test_sin_universe_yaml_el_limite_por_grupo_falla_con_la_ruta(tmp_path):
    """Y no arranca un backtest que aplicaría el límite a medias."""
    import subprocess

    raiz = Path(__file__).resolve().parents[1]
    proceso = subprocess.run(
        [
            sys.executable, "-m", "tradingbot.cli", "backtest",
            "--strategy", str(raiz / "config/strategies/cartera_correlacionada.yaml"),
            "--data", str(raiz / "tests/fixtures/correlated"),
            "--universe", str(tmp_path / "no_existe.yaml"),
        ],
        capture_output=True, text=True, cwd=raiz,
    )
    assert proceso.returncode == 2
    assert "no_existe.yaml" in proceso.stderr
    assert "max_per_group" in proceso.stderr
