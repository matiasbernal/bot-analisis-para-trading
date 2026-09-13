"""Trailing chandelier: la capa que cierra la tanda 2A.

Entra **por decisión de diseño del PLAN** ("las plantillas arrancan con dos capas
prendidas: hard stop + trailing"), no porque se haya medido que aporta. Estos
tests verifican el MOTOR —que la capa hace lo que dice— y no que la capa sea
buena; la distinción está escrita en ESTADO.md, sección 2, y es la que evita que
un test en verde sobre datos sintéticos se lea como validación de la estrategia.

Las velas van a mano para que el nivel del chandelier sea un número exacto y no
haya que confiar en un generador: con veintiuna velas planas y después una
escalera de +1 por vela, el rango verdadero es 1.0 en **todas** las barras, así
que ATR(5) vale exactamente 1.0 y el chandelier queda en ``máximo − 3``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_strategy
from fixtures.candles import flat, frame

from tradingbot.backtest.engine import run_backtest
from tradingbot.data.validate import validate_ohlcv
from tradingbot.strategy.exits import chandelier_stop, stop_reasons
from tradingbot.strategy.position import Position

#: velas planas antes de la señal. La entrada cae en la primera de la escalera.
WARMUP = 21
ATR_PERIODO = 5
MULTIPLO = 3.0

#: con hard_stop pct=5 sobre un cierre de 100: 1R = 5, stop inicial 95, objetivo 115
ENTRADA = 100.0
UN_R = 5.0
STOP_INICIAL = 95.0
OBJETIVO = 115.0


def escalera(desde: float, hasta: float) -> list[tuple[float, float, float, float]]:
    """Velas de +1 por día con rango verdadero exactamente 1.0.

    ``open = cierre anterior``, ``high = open + 1``, ``low = open``,
    ``close = high``. Así TR = max(h−l, |h−pc|, |l−pc|) = max(1, 1, 0) = 1 en cada
    barra, y el ATR de Wilder no se mueve de 1.0 mientras dure la escalera.
    """
    return [(float(p), float(p) + 1.0, float(p), float(p) + 1.0) for p in range(int(desde), int(hasta))]


def _run(bars, *, trailing: dict | None = None, **overrides):
    """Corre el motor con la entrada forzada en la primera vela de la escalera."""
    df = validate_ohlcv(frame(bars), "TEST")
    exits = {
        "hard_stop": {"mode": "pct", "pct": 5.0},
        "take_profit": {"mode": "rr", "ratio": 3.0},
    }
    if trailing is not None:
        exits["trailing_stop"] = {
            "mode": "chandelier",
            "multiple": MULTIPLO,
            "atr_period": ATR_PERIODO,
            **trailing,
        }
    config = make_strategy(
        warmup_bars=WARMUP - 1, universe=["TEST"], exits=exits, **overrides
    )
    return run_backtest(config, {"TEST": df})


@pytest.fixture
def espia_stop(monkeypatch):
    """Registra cada intento de mover el stop: (antes, propuesto, después).

    Es la única forma de ver el camino del stop desde afuera del motor: el
    ``Trade`` cerrado guarda el stop inicial y el precio de salida, pero no por
    dónde pasó el stop en el medio, que es justamente lo que la invariante 1 de
    ``position.py`` promete.
    """
    intentos: list[tuple[float, float, float]] = []
    original = Position.raise_stop

    def espiado(self, new_stop, **kwargs):
        antes = self.stop_current
        movio = original(self, new_stop, **kwargs)
        intentos.append((antes, float(new_stop), self.stop_current))
        return movio

    monkeypatch.setattr(Position, "raise_stop", espiado)
    return intentos


# --- la aritmética, aislada -------------------------------------------------
def test_el_nivel_es_el_maximo_menos_multiplo_por_atr():
    assert chandelier_stop(110.0, 2.0, 3.0) == pytest.approx(104.0)
    assert chandelier_stop(112.0, 1.0, 3.0) == pytest.approx(109.0)


def test_sin_atr_el_nivel_no_existe_y_no_mueve_el_stop():
    """En el warmup el ATR es NaN: el stop se queda donde está, no salta a nada."""
    nivel = chandelier_stop(110.0, float("nan"), 3.0)
    assert nivel != nivel  # NaN

    position = Position(
        symbol="TEST",
        entry_date=None,
        entry_price=ENTRADA,
        shares=10,
        risk_per_share=UN_R,
        stop_current=STOP_INICIAL,
        peak_price=110.0,
    )
    assert position.raise_stop(nivel) is False
    assert position.stop_current == STOP_INICIAL
    assert position.stop_moves == 0


# --- 2.1 el stop nunca baja, contra el motor --------------------------------
def test_el_stop_nunca_baja_aunque_el_chandelier_proponga_bajarlo(espia_stop):
    """Un ATR que se agranda después del pico propone un nivel más bajo.

    Es el caso que hace falta ver: la escalera deja el stop en 109 y después
    llega una vela ancha (TR = 2.5, o sea ATR 1.3) que baja el chandelier a
    108.5 − 3.9 = 104.6. Si el trailing fuera una asignación en vez de
    ``raise_stop``, el stop bajaría 4.4 puntos justo cuando el trade empieza a
    darse vuelta, que es el error más caro que puede cometer esta capa.
    """
    bars = (
        flat(WARMUP)
        + escalera(100, 112)                    # máximo 112, ATR 1.0 -> stop 109
        + [(112.0, 112.5, 110.0, 110.5)]        # TR 2.5 -> ATR 1.3, chandelier 104.6
        + [(110.5, 111.0, 110.0, 110.5)]
    )
    result = _run(bars, trailing={"activate_after_r": 1.0})

    bajadas = [i for i in espia_stop if i[1] < i[0]]
    assert bajadas, "ninguna vela propuso bajar el stop: el test no prueba nada"
    for antes, propuesto, despues in espia_stop:
        assert despues >= antes, f"el stop bajó de {antes} a {despues}"
    for antes, propuesto, despues in bajadas:
        assert despues == antes, "un nivel peor movió el stop igual"

    # y el camino que sí recorrió: monótono creciente desde el stop inicial
    alcanzados = [i[2] for i in espia_stop]
    assert alcanzados == sorted(alcanzados)
    assert alcanzados[0] >= STOP_INICIAL
    assert max(alcanzados) == pytest.approx(109.0)


def test_el_stop_no_baja_en_ninguna_posicion_del_universo_correlacionado(espia_stop):
    """La misma invariante, sobre 10 símbolos y 1250 velas en vez de a mano."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from fixtures.synthetic import correlated_universe

    frames = {s: validate_ohlcv(df, s) for s, df in correlated_universe().items()}
    config = make_strategy(
        universe=list(frames),
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
            "trailing_stop": {"mode": "chandelier", "multiple": 3.0, "activate_after_r": 1.0},
            "take_profit": {"ratio": 3.0},
        },
        risk={"position_sizing": {"risk_pct": 1.0}, "max_position_pct": 30.0},
    )
    result = run_backtest(config, frames)

    assert result.trades, "el backtest no abrió ninguna posición"
    assert espia_stop, "el trailing no intentó mover el stop ni una vez"
    for antes, propuesto, despues in espia_stop:
        assert despues >= antes, f"el stop bajó de {antes} a {despues}"


# --- 2.2 activate_after_r: 1.0 ----------------------------------------------
def test_sin_llegar_a_1r_el_trailing_no_se_activa():
    """Sube hasta +0.9R y se da vuelta: tiene que salir por el hard stop, en 95.

    El pico son 104.5 —104 de la escalera y medio punto más del máximo de la vela
    que se da vuelta—, o sea 0.9R: cerca del umbral pero abajo. Si el trailing se
    activara sin umbral, el chandelier estaría en 104.5 − 3 = 101.5 y la salida
    sería ahí, con motivo ``trailing_stop``. Que salga en 95 por ``hard_stop`` es
    la prueba de que el armado respetó el umbral.
    """
    bars = (
        flat(WARMUP)
        + escalera(100, 104)                  # máximo 104.5 con la vela roja -> +0.9R
        + [(104.0, 104.5, 94.0, 95.0)]        # se da vuelta hasta el stop inicial
        + [(95.0, 95.5, 94.5, 95.0)]
    )
    result = _run(bars, trailing={"activate_after_r": 1.0})
    trade = result.trades[0]

    assert trade.mfe_r == pytest.approx(0.9)
    assert trade.exit_reasons == ["hard_stop"]
    assert trade.exit_price == pytest.approx(STOP_INICIAL)


def test_al_cruzar_1r_se_arma_y_ya_no_se_desarma():
    """Toca +1R, retrocede por debajo del umbral, y el trailing sigue puesto.

    El armado es de una sola vía (invariante 3 de ``position.py``): si se
    desactivara al retroceder, el trailing se soltaría justo durante el retroceso,
    que es cuando tiene que agarrar.
    """
    bars = (
        flat(WARMUP)
        + escalera(100, 106)                  # máximo 106 -> +1.2R: arma, stop 103
        + [(106.0, 106.0, 103.5, 104.0)]      # retrocede a +0.8R, el stop no se toca
        + [(104.0, 104.5, 102.0, 102.5)]      # y ahí sí lo agarra el trailing en 103
    )
    result = _run(bars, trailing={"activate_after_r": 1.0})
    trade = result.trades[0]

    assert trade.exit_reasons == ["trailing_stop"]
    assert trade.exit_price == pytest.approx(103.0)
    assert trade.pnl_r > 0, "el trailing sacó el trade con ganancia asegurada"


def test_con_activate_after_r_en_cero_el_trailing_manda_desde_la_entrada():
    bars = (
        flat(WARMUP)
        + escalera(100, 104)
        + [(104.0, 104.5, 94.0, 95.0)]
        + [(95.0, 95.5, 94.5, 95.0)]
    )
    result = _run(bars, trailing={"activate_after_r": 0.0})
    trade = result.trades[0]

    # máximo 104, ATR 1.0 -> el chandelier ya estaba en 101 cuando llegó la caída
    assert trade.exit_reasons == ["trailing_stop"]
    assert trade.exit_price == pytest.approx(101.0)


# --- 2.5 las tres velas a mano ----------------------------------------------
def test_gap_por_debajo_del_trailing_llena_en_la_apertura():
    """Abre en 104 con el trailing en 109: el fill es 104, no 109.

    Es la misma regla que el gap contra el hard stop —el peor caso para el
    trade—, pero con su propio motivo: ``gap_trailing_stop``. Sin esa distinción,
    la atribución le carga al hard stop una salida que decidió el trailing.
    """
    bars = (
        flat(WARMUP)
        + escalera(100, 112)                  # máximo 112 -> stop del trailing en 109
        + [(104.0, 105.0, 103.0, 104.0)]      # abre 5 puntos por debajo del stop
        + [(104.0, 104.5, 103.5, 104.0)]
    )
    result = _run(bars, trailing={"activate_after_r": 1.0})
    trade = result.trades[0]

    assert trade.exit_reasons == ["gap_trailing_stop"]
    assert trade.exit_price == pytest.approx(104.0)
    assert trade.exit_price < 109.0
    assert trade.exit_price > trade.stop_initial, "salió arriba del hard stop, no debajo"


def test_trailing_y_objetivo_en_la_misma_vela_gana_el_trailing():
    """Toca 116 (objetivo 115) y 108 (trailing 109) en la misma vela: gana el stop.

    Es la regla de rigor 4 del PLAN, que no cambia porque el stop lo haya movido
    el trailing: con velas diarias no se sabe cuál de los dos ocurrió primero, y
    el criterio conservador es el peor caso.
    """
    bars = (
        flat(WARMUP)
        + escalera(100, 112)                  # máximo 112 -> stop del trailing en 109
        + [(112.0, 116.0, 108.0, 110.0)]      # toca el objetivo 115 y el stop 109
        + [(110.0, 110.5, 109.5, 110.0)]
    )
    result = _run(bars, trailing={"activate_after_r": 1.0})
    trade = result.trades[0]

    assert trade.exit_reasons == ["trailing_stop"]
    assert trade.exit_price == pytest.approx(109.0)
    assert trade.pnl_r == pytest.approx((109.0 - ENTRADA) / UN_R, abs=0.02)


def test_sin_trailing_la_misma_vela_sale_por_el_objetivo():
    """La contraprueba: sin la capa, esa vela es un take profit de +3R.

    Sirve para ver que el test de arriba mide el trailing y no otra cosa, y de
    paso deja escrito el precio que la capa dejó sobre la mesa en este caso: 6
    puntos, o sea 1.2R.
    """
    bars = (
        flat(WARMUP)
        + escalera(100, 112)
        + [(112.0, 116.0, 108.0, 110.0)]
        + [(110.0, 110.5, 109.5, 110.0)]
    )
    result = _run(bars, trailing=None)
    trade = result.trades[0]

    assert trade.exit_reasons == ["take_profit"]
    assert trade.exit_price == pytest.approx(OBJETIVO)


# --- 2.3 la atribución ------------------------------------------------------
def test_el_motivo_lo_pone_la_capa_que_movio_el_stop():
    """``stop_reasons`` es lo que separa hard stop de trailing en la atribución."""
    position = Position(
        symbol="TEST",
        entry_date=None,
        entry_price=ENTRADA,
        shares=10,
        risk_per_share=UN_R,
        stop_current=STOP_INICIAL,
        peak_price=ENTRADA,
    )
    assert stop_reasons(position) == ("gap_stop", "hard_stop")

    position.raise_stop(102.0, source="trailing_stop")
    assert position.stop_source == "trailing_stop"
    assert stop_reasons(position) == ("gap_trailing_stop", "trailing_stop")

    # un nivel peor no se lleva el crédito: el stop no se movió, la fuente tampoco
    assert position.raise_stop(101.0, source="break_even") is False
    assert stop_reasons(position) == ("gap_trailing_stop", "trailing_stop")


# --- las dos plantillas, y lo que el informe tiene que decir ----------------
def test_las_dos_plantillas_difieren_solo_en_el_trailing():
    """``ema_cross`` y ``ema_cross_sin_trailing`` son el par del banco A/B.

    Si se separan en cualquier otra cosa —otro universo, otro tope, otro
    objetivo—, el banco deja de medir la capa y pasa a medir dos estrategias
    distintas, que es exactamente el error que el banco existe para evitar. Las
    diferencias permitidas son tres y están enumeradas.
    """
    import yaml

    con = yaml.safe_load(
        Path("config/strategies/ema_cross.yaml").read_text(encoding="utf-8")
    )
    sin = yaml.safe_load(
        Path("config/strategies/ema_cross_sin_trailing.yaml").read_text(encoding="utf-8")
    )

    assert "trailing_stop" in con["exits"], (
        "la plantilla perdió el trailing: el PLAN dice que la línea base son dos "
        "capas prendidas, hard stop + trailing"
    )
    assert "trailing_stop" not in sin["exits"]

    con.pop("calibration"), sin.pop("calibration")
    con.pop("name"), sin.pop("name")
    con["exits"].pop("trailing_stop")
    assert con == sin, "las dos plantillas se separaron en algo que no es el trailing"


def test_el_informe_dice_que_el_trailing_entra_por_diseno_y_no_medido():
    """2.4: donde aparezca el trailing tiene que estar el aviso, como el de rango."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from fixtures.synthetic import synthetic_universe

    from tradingbot.config import load_strategy
    from tradingbot.reporting.report import TRAILING_NO_VALIDADO, render_console

    config = load_strategy("config/strategies/ema_cross.yaml")
    frames = {
        s: validate_ohlcv(df, s) for s, df in synthetic_universe(config.universe).items()
    }
    texto = render_console(run_backtest(config, frames))

    assert "PRENDIDO POR DISEÑO" in TRAILING_NO_VALIDADO
    assert TRAILING_NO_VALIDADO in texto
    # y la tabla de atribución tiene su fila y su nota al pie
    assert "trailing_stop" in texto
    assert "no porque se haya medido que aporta" in texto
    # el bloque de poder también lo aclara, porque ahí la fila parece candidata
    assert "trailing_stop NO es candidata del torneo" in texto


def test_sin_trailing_el_informe_no_trae_el_aviso():
    """El aviso es del trailing, no decorado permanente: sin la capa no aparece."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from fixtures.synthetic import synthetic_universe

    from tradingbot.config import load_strategy
    from tradingbot.reporting.report import TRAILING_NO_VALIDADO, render_console

    config = load_strategy("config/strategies/ema_cross_sin_trailing.yaml")
    frames = {
        s: validate_ohlcv(df, s) for s, df in synthetic_universe(config.universe).items()
    }
    texto = render_console(run_backtest(config, frames))

    assert TRAILING_NO_VALIDADO not in texto


def test_el_banco_ab_aclara_que_el_empate_no_apaga_el_trailing():
    """El veredicto genérico dice "queda APAGADA" y para el trailing eso engaña.

    El banco aplica las dos reglas de desempate del PLAN sin saber qué capa está
    comparando. Cuando la capa que cambia es el trailing —que no compite— la
    frase se lee al revés de lo que corresponde, así que la CLI la corrige justo
    abajo del veredicto.
    """
    import subprocess
    import sys

    raiz = Path(__file__).resolve().parents[1]
    proceso = subprocess.run(
        [
            sys.executable, "-m", "tradingbot.cli", "comparar",
            "--base", str(raiz / "config/strategies/ema_cross_sin_trailing.yaml"),
            "--variante", str(raiz / "config/strategies/ema_cross.yaml"),
            "--data", str(raiz / "tests/fixtures/synthetic"),
            "--replicas", "500",
        ],
        capture_output=True, text=True, cwd=raiz,
    )
    assert proceso.returncode == 0, proceso.stderr
    salida = proceso.stdout

    assert "OJO CON ESTE VEREDICTO" in salida
    assert "NO es candidata del torneo" in salida
    assert "sigue prendido por diseño" in salida
    # y el banco igual hizo su trabajo: emparejó y midió
    assert "delta pareado" in salida and "trades afectados" in salida
