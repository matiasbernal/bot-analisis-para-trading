"""El universo correlacionado: lo que hace falta para probar riesgo de cartera.

Los fixtures de la tanda 1 son independientes entre sí (ρ ≈ -0.01 medida). Sobre
eso, una cartera de cuatro símbolos muestra la mitad del drawdown de sus
componentes, y esa reducción es puro artificio del generador: en el mercado real
AAPL, MSFT, QQQ y SPY se mueven casi juntos (ρ diaria 0.70 a 0.92). Todo lo que
la tanda 2 construya sobre correlación —heat de cartera, límite por grupo, "cinco
tecnológicas no son cinco posiciones"— se vería el doble de bueno de lo que es.

El universo correlacionado vive **al lado** del otro, no lo reemplaza: los
números de la tanda 1 quedan donde están.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fixtures.synthetic import (
    CORRELATED_UNIVERSE,
    GRUPOS,
    RHO_INTER,
    RHO_INTRA,
    RHO_MERCADO,
    correlated_universe,
    correlation_matrix,
    grupo_de,
    synthetic_universe,
)

from tradingbot.backtest.metrics import max_drawdown
from tradingbot.data.validate import validate_ohlcv

#: Tolerancias del cotejo pedida-vs-realizada. El modelo produce la correlación
#: pedida en la POBLACIÓN; sobre 1250 barras el error muestral por par es del
#: orden de 1/√1250 ≈ 0.028, y además los errores de distintos pares no son
#: independientes (comparten el mismo sorteo del factor común), así que toda una
#: categoría se puede correr junta unas centésimas.
TOLERANCIA_PAR = 0.07       # par individual contra su valor pedido
TOLERANCIA_CATEGORIA = 0.05  # media de una categoría (intra, entre, índice)


@pytest.fixture(scope="module")
def universo():
    return correlated_universe()


@pytest.fixture(scope="module")
def retornos(universo):
    return pd.DataFrame(
        {s: df["close"].pct_change() for s, df in universo.items()}
    ).dropna()


def test_las_series_cumplen_el_contrato_ohlcv(universo):
    for symbol, df in universo.items():
        validado = validate_ohlcv(df, symbol)
        assert len(validado) == 1250


def test_es_deterministico():
    uno, dos = correlated_universe(bars=200), correlated_universe(bars=200)
    for symbol in uno:
        assert uno[symbol].equals(dos[symbol])
    otro = correlated_universe(bars=200, seed=999)
    assert not uno["SPY"].equals(otro["SPY"])


# --- la correlación pedida es la que sale ----------------------------------
def test_la_correlacion_realizada_es_la_pedida(retornos):
    pedida = correlation_matrix(list(retornos.columns))
    realizada = retornos.corr()
    error = (realizada - pedida).abs().to_numpy()
    assert error[np.triu_indices(len(retornos.columns), 1)].max() < TOLERANCIA_PAR


def test_la_estructura_de_grupos_se_distingue(retornos):
    """Alta adentro del grupo, baja entre grupos: eso es lo que le da trabajo a
    ``max_per_group``. Con una ρ uniforme, un límite por sector no se podría
    distinguir de un límite de heat total."""
    matriz = retornos.corr()
    symbols = list(retornos.columns)

    intra = [
        matriz.loc[a, b]
        for i, a in enumerate(symbols)
        for b in symbols[i + 1 :]
        if grupo_de(a) == grupo_de(b)
    ]
    entre = [
        matriz.loc[a, b]
        for i, a in enumerate(symbols)
        for b in symbols[i + 1 :]
        if grupo_de(a) != grupo_de(b) and "mercado" not in (grupo_de(a), grupo_de(b))
    ]
    contra_indice = [matriz.loc[s, "SPY"] for s in symbols if s != "SPY"]

    assert np.mean(intra) == pytest.approx(RHO_INTRA, abs=TOLERANCIA_CATEGORIA)
    assert np.mean(entre) == pytest.approx(RHO_INTER, abs=TOLERANCIA_CATEGORIA)
    assert np.mean(contra_indice) == pytest.approx(RHO_MERCADO, abs=TOLERANCIA_CATEGORIA)
    assert min(intra) > max(entre)  # los grupos se separan sin solaparse


def test_acepta_una_rho_uniforme(retornos):
    uniforme = correlated_universe(bars=600, corr=0.9)
    rets = pd.DataFrame({s: df["close"].pct_change() for s, df in uniforme.items()}).dropna()
    fuera = rets.corr().to_numpy()[np.triu_indices(len(rets.columns), 1)]
    assert fuera.mean() == pytest.approx(0.9, abs=TOLERANCIA_CATEGORIA)


def test_rechaza_una_matriz_imposible():
    symbols = list(CORRELATED_UNIVERSE)[:3]
    imposible = pd.DataFrame(
        [[1.0, 0.99, -0.99], [0.99, 1.0, 0.99], [-0.99, 0.99, 1.0]],
        index=symbols,
        columns=symbols,
    )
    specs = {s: CORRELATED_UNIVERSE[s] for s in symbols}
    with pytest.raises(ValueError, match="no es definida positiva"):
        correlated_universe(specs, corr=imposible, bars=100)


# --- los gaps, que es lo que hace saltar varios stops la misma mañana -------
def _gaps(universo) -> pd.DataFrame:
    return pd.DataFrame(
        {s: df["open"] / df["close"].shift(1) - 1 for s, df in universo.items()}
    ).dropna()


def test_los_gaps_se_abren_juntos(universo):
    """Por defecto los gaps siguen la misma estructura que los retornos."""
    matriz = _gaps(universo).corr()
    symbols = list(universo)
    intra = [
        matriz.loc[a, b]
        for i, a in enumerate(symbols)
        for b in symbols[i + 1 :]
        if grupo_de(a) == grupo_de(b)
    ]
    assert np.mean(intra) == pytest.approx(RHO_INTRA, abs=TOLERANCIA_CATEGORIA)


def test_gap_corr_se_puede_controlar_aparte():
    """Retornos correlacionados pero gaps independientes: el caso de control."""
    universo = correlated_universe(gap_corr=0.0, bars=800)
    fuera = _gaps(universo).corr().to_numpy()[np.triu_indices(len(universo), 1)]
    assert abs(fuera.mean()) < TOLERANCIA_CATEGORIA

    # y los retornos siguen correlacionados
    rets = pd.DataFrame(
        {s: df["close"].pct_change() for s, df in universo.items()}
    ).dropna()
    assert rets.corr().loc["AAPL", "MSFT"] == pytest.approx(RHO_INTRA, abs=TOLERANCIA_PAR)


def test_con_gaps_correlacionados_hay_mañanas_de_hueco_generalizado(universo):
    """El escenario que el heat de cartera tiene que sobrevivir: varios símbolos
    abriendo con hueco a la baja el mismo día."""
    gaps = _gaps(universo)
    fuertes = (gaps < -0.005).sum(axis=1)  # símbolos con gap < -0.5% ese día
    simultaneos = int((fuertes >= 4).sum())

    sin_correlacion = _gaps(correlated_universe(gap_corr=0.0))
    aislados = int(((sin_correlacion < -0.005).sum(axis=1) >= 4).sum())

    assert simultaneos > 3 * max(aislados, 1), (
        f"con gaps correlacionados hubo {simultaneos} mañanas de hueco generalizado "
        f"y sin correlación {aislados}: la diferencia tiene que ser grande"
    )


# --- test de cordura: la diversificación deja de ser un regalo -------------
def _equiponderada(universo) -> pd.Series:
    return sum(df["close"] / df["close"].iloc[0] for df in universo.values()) / len(universo)


def test_la_correlacion_se_come_la_diversificacion(universo):
    """La medida correcta es la volatilidad de la cartera contra la de sus partes.

    Con 8 símbolos el MDD de la cartera daba el 86% del promedio de sus
    componentes, y lo usé como criterio. Con 10 ya no: promediar más series
    siempre baja el drawdown de la cartera contra el del componente promedio,
    haya o no correlación, así que ese ratio mide la cantidad de símbolos tanto
    como la correlación. La medida limpia es el cociente de volatilidades, que
    con ρ=0 tiende a 1/√n y con ρ=1 a 1.
    """
    correlacionado = pd.DataFrame(
        {s: df["close"].pct_change() for s, df in universo.items()}
    ).dropna()
    independiente = pd.DataFrame(
        {
            s: df["close"].pct_change()
            for s, df in correlated_universe(corr=0.0).items()
        }
    ).dropna()

    def cociente(rets):
        return float(rets.mean(axis=1).std() / rets.std().mean())

    assert cociente(correlacionado) > 0.70   # medido: 0.78
    assert cociente(independiente) < 0.40    # medido: 0.32

    # y el drawdown de la cartera correlacionada es mucho peor que el de la misma
    # cartera sin correlación: eso es lo que el heat tiene que sobrevivir
    cartera_corr = max_drawdown(_equiponderada(universo))
    cartera_indep = max_drawdown(_equiponderada(correlated_universe(corr=0.0)))
    assert cartera_corr / cartera_indep > 1.8   # medido: 2.19


def test_el_universo_de_la_tanda_1_regala_diversificacion(universo):
    """El contraste que motivó todo esto: 4 series independientes."""
    viejo = synthetic_universe()
    componentes = float(np.mean([max_drawdown(df["close"]) for df in viejo.values()]))
    assert max_drawdown(_equiponderada(viejo)) / componentes < 0.60


def test_los_fixtures_commiteados_son_los_que_genera_el_script():
    """Si alguien toca el generador, los CSV del repo dejan de coincidir."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    for carpeta, universo in (
        ("synthetic", synthetic_universe()),
        ("correlated", correlated_universe()),
    ):
        for symbol, esperado in universo.items():
            path = raiz / carpeta / f"{symbol}.csv"
            assert path.is_file(), f"falta {path}"
            commiteado = pd.read_csv(path, index_col="date", parse_dates=True, encoding="utf-8")
            commiteado.index.name = "date"
            pd.testing.assert_frame_equal(
                commiteado, esperado, check_freq=False, rtol=0, atol=0
            )


def test_los_grupos_cubren_todo_el_universo():
    declarados = {s for symbols in GRUPOS.values() for s in symbols}
    assert declarados == set(CORRELATED_UNIVERSE)
    assert all(grupo_de(s) != "otros" for s in CORRELATED_UNIVERSE)


# --- lo que el fixture tiene que poder producir para la tanda 2 -------------
def test_hay_grupos_con_margen_sobre_un_tope_de_2():
    """Con dos símbolos por grupo, ``max_per_group: 2`` no se puede violar nunca.

    Hace falta al menos un grupo de 4 (tres señales dejan una afuera y todavía
    sobra margen) y otro de 3.
    """
    tamanos = sorted((len(s) for s in GRUPOS.values()), reverse=True)
    assert tamanos[0] >= 4, f"ningún grupo llega a 4 símbolos: {tamanos}"
    assert tamanos[1] >= 3, f"solo un grupo pasa de 2 símbolos: {tamanos}"


def test_el_fixture_produce_tres_posiciones_simultaneas_del_mismo_grupo():
    """El escenario que ``max_per_group: 2`` tiene que rechazar, sobre datos.

    No basta con que el grupo tenga 4 símbolos: la correlación tiene que hacer
    que entren juntos. Se cuenta, sobre una estrategia de cruce de medias sin
    límite por grupo, cuántos días-grupo hubo con 3 o más posiciones abiertas
    del mismo sector. Esos son los que la Fase 3 va a tener que rechazar.
    """
    from collections import Counter

    from conftest import make_strategy

    from tradingbot.backtest.engine import run_backtest

    frames = {
        s: validate_ohlcv(df, s) for s, df in correlated_universe().items()
    }
    config = make_strategy(
        universe=list(frames),
        warmup_bars=200,
        indicators={
            "ema_fast": {"type": "ema", "period": 20},
            "ema_slow": {"type": "ema", "period": 50},
        },
        entry={"all": [{"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}]},
        exits={
            "signal": {"any": [{"left": "ema_fast", "op": "crosses_below", "right": "ema_slow"}]},
            "hard_stop": {"mode": "atr", "multiple": 2.0},
            "take_profit": {"ratio": 3.0},
        },
        risk={
            "position_sizing": {"risk_pct": 1.0},
            "max_position_pct": 30.0,
            "max_open_positions": 10,  # sin tope: se quiere ver el caso crudo
        },
    )
    result = run_backtest(config, frames)

    abiertas: Counter = Counter()
    for trade in result.trades:
        for dia in pd.bdate_range(trade.entry_date, trade.exit_date):
            abiertas[(dia, grupo_de(trade.symbol))] += 1

    concurrentes = Counter(abiertas.values())
    con_3 = sum(v for k, v in concurrentes.items() if k >= 3)
    con_4 = sum(v for k, v in concurrentes.items() if k >= 4)

    assert con_3 >= 50, (
        f"solo {con_3} días-grupo con 3+ posiciones del mismo sector: el fixture no "
        "alcanza para probar max_per_group"
    )
    assert con_4 >= 10, (
        f"solo {con_4} días-grupo con 4+: no hay margen por encima de un tope de 2"
    )
