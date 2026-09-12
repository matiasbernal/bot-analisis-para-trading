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

#: error muestral esperable con 1250 barras: ~1/√1250 ≈ 0.028
TOLERANCIA_RHO = 0.05


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
    assert error[np.triu_indices(len(retornos.columns), 1)].max() < TOLERANCIA_RHO


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

    assert np.mean(intra) == pytest.approx(RHO_INTRA, abs=TOLERANCIA_RHO)
    assert np.mean(entre) == pytest.approx(RHO_INTER, abs=TOLERANCIA_RHO)
    assert np.mean(contra_indice) == pytest.approx(RHO_MERCADO, abs=TOLERANCIA_RHO)
    assert min(intra) > max(entre)  # los grupos se separan sin solaparse


def test_acepta_una_rho_uniforme(retornos):
    uniforme = correlated_universe(bars=600, corr=0.9)
    rets = pd.DataFrame({s: df["close"].pct_change() for s, df in uniforme.items()}).dropna()
    fuera = rets.corr().to_numpy()[np.triu_indices(len(rets.columns), 1)]
    assert fuera.mean() == pytest.approx(0.9, abs=TOLERANCIA_RHO)


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
    assert np.mean(intra) == pytest.approx(RHO_INTRA, abs=TOLERANCIA_RHO)


def test_gap_corr_se_puede_controlar_aparte():
    """Retornos correlacionados pero gaps independientes: el caso de control."""
    universo = correlated_universe(gap_corr=0.0, bars=800)
    fuera = _gaps(universo).corr().to_numpy()[np.triu_indices(len(universo), 1)]
    assert abs(fuera.mean()) < TOLERANCIA_RHO

    # y los retornos siguen correlacionados
    rets = pd.DataFrame(
        {s: df["close"].pct_change() for s, df in universo.items()}
    ).dropna()
    assert rets.corr().loc["AAPL", "MSFT"] == pytest.approx(RHO_INTRA, abs=TOLERANCIA_RHO)


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
def test_la_cartera_ya_no_muestra_la_mitad_del_drawdown(universo):
    """Con ρ realista, el MDD de la cartera se parece al de sus componentes."""
    componentes = [max_drawdown(df["close"]) for df in universo.values()]
    promedio = float(np.mean(componentes))

    equiponderada = sum(
        df["close"] / df["close"].iloc[0] for df in universo.values()
    ) / len(universo)
    cartera = max_drawdown(equiponderada)

    assert cartera / promedio > 0.75, (
        f"la cartera correlacionada muestra {cartera:.1%} contra un promedio de "
        f"{promedio:.1%} en sus componentes: demasiada diversificación gratis"
    )

    # el universo de la tanda 1, para contraste: ahí sí es un regalo
    viejo = synthetic_universe()
    comp_viejo = float(np.mean([max_drawdown(df["close"]) for df in viejo.values()]))
    eq_viejo = sum(df["close"] / df["close"].iloc[0] for df in viejo.values()) / len(viejo)
    assert max_drawdown(eq_viejo) / comp_viejo < 0.60


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
            commiteado = pd.read_csv(path, index_col="date", parse_dates=True)
            commiteado.index.name = "date"
            pd.testing.assert_frame_equal(
                commiteado, esperado, check_freq=False, rtol=0, atol=0
            )


def test_los_grupos_cubren_todo_el_universo():
    declarados = {s for symbols in GRUPOS.values() for s in symbols}
    assert declarados == set(CORRELATED_UNIVERSE)
    assert all(grupo_de(s) != "otros" for s in CORRELATED_UNIVERSE)
