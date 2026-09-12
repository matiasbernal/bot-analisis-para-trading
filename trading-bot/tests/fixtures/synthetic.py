"""Generador determinístico de OHLCV. No necesita red.

Random walk con drift y volatilidad configurables y ``seed`` fijo: la misma
llamada devuelve siempre exactamente la misma serie, en cualquier máquina. Es lo
que permite testear el motor, los costos y el sizing sin depender de Yahoo.

Un backtest sobre datos sintéticos con drift positivo **tiene** que dar
resultados coherentes con ese drift; es un test de cordura barato.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_BARS = 1250  # ~5 años de velas diarias


def synthetic_ohlcv(
    *,
    bars: int = DEFAULT_BARS,
    start: str = "2018-01-01",
    seed: int = 42,
    start_price: float = 100.0,
    drift: float = 0.0004,
    volatility: float = 0.012,
    gap_volatility: float = 0.003,
    base_volume: int = 2_000_000,
) -> pd.DataFrame:
    """Devuelve un OHLCV válido según el contrato de ``data/validate.py``."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(start=start, periods=bars, name="date")

    shocks = rng.normal(drift, volatility, size=bars)
    gaps = rng.normal(0.0, gap_volatility, size=bars)
    return _ohlcv_from_shocks(
        shocks,
        gaps,
        rng=rng,
        index=index,
        start_price=start_price,
        volatility=volatility,
        base_volume=base_volume,
    )


def _ohlcv_from_shocks(
    shocks: np.ndarray,
    gaps: np.ndarray,
    *,
    rng: np.random.Generator,
    index: pd.DatetimeIndex,
    start_price: float,
    volatility: float,
    base_volume: int,
) -> pd.DataFrame:
    """Arma el OHLCV a partir de los shocks de cierre y los gaps de apertura.

    Lo comparten ``synthetic_ohlcv`` (shocks independientes) y
    ``correlated_universe`` (shocks correlacionados entre símbolos). El orden en
    que se consume el ``rng`` es parte del contrato: cambiarlo cambia todos los
    fixtures generados.
    """
    bars = len(shocks)
    closes = start_price * np.exp(np.cumsum(shocks))

    prev_close = np.concatenate([[start_price], closes[:-1]])
    opens = prev_close * (1.0 + gaps)

    # rango intrabar: siempre contiene a open y close
    spread = np.abs(rng.normal(0.0, volatility, size=bars)) * closes
    highs = np.maximum(opens, closes) + spread * rng.uniform(0.1, 1.0, size=bars)
    lows = np.minimum(opens, closes) - spread * rng.uniform(0.1, 1.0, size=bars)
    lows = np.minimum(lows, np.minimum(opens, closes))
    lows = np.maximum(lows, 0.01)

    volume = (base_volume * rng.uniform(0.5, 1.8, size=bars)).astype("int64")

    return pd.DataFrame(
        {
            "open": np.round(opens, 4),
            "high": np.round(highs, 4),
            "low": np.round(lows, 4),
            "close": np.round(closes, 4),
            "volume": volume,
        },
        index=index,
    )


#: Universo sintético del sandbox.
#:
#: OJO CON LOS NOMBRES: estas series **no son datos de mercado**. Son random
#: walks determinísticos etiquetados AAPL/MSFT/SPY/QQQ para que las plantillas
#: corran sin red. No se parecen a esos papeles ni pretenden hacerlo: sirven
#: para probar el motor, no para sacar conclusiones sobre ninguna estrategia.
#: Los datos reales van en tests/fixtures/SPY.csv y AAPL.csv, que se generan
#: con scripts/fetch_fixture.py y tienen precedencia sobre estos.
SYNTHETIC_UNIVERSE: dict[str, dict] = {
    "AAPL": {"seed": 11, "start_price": 120.0, "drift": 0.0006, "volatility": 0.016},
    "MSFT": {"seed": 22, "start_price": 180.0, "drift": 0.0005, "volatility": 0.014},
    "SPY": {"seed": 33, "start_price": 260.0, "drift": 0.0004, "volatility": 0.010},
    "QQQ": {"seed": 44, "start_price": 150.0, "drift": 0.0005, "volatility": 0.013},
}


def synthetic_universe(
    symbols: list[str] | None = None, *, bars: int = DEFAULT_BARS, start: str = "2018-01-01"
) -> dict[str, pd.DataFrame]:
    """Las series sintéticas del universo, por símbolo.

    **Sin correlación entre símbolos** (ρ medida ≈ -0.01). Para cualquier cosa
    que dependa de cómo se mueven juntos —heat de cartera, límite por grupo,
    diversificación— usar ``correlated_universe``.
    """
    chosen = symbols or list(SYNTHETIC_UNIVERSE)
    out: dict[str, pd.DataFrame] = {}
    for symbol in chosen:
        params = SYNTHETIC_UNIVERSE.get(symbol, {"seed": abs(hash(symbol)) % 10_000})
        out[symbol] = synthetic_ohlcv(bars=bars, start=start, **params)
    return out


# ---------------------------------------------------------------------------
# Universo correlacionado
# ---------------------------------------------------------------------------
#: Grupos del universo correlacionado. La estructura importa: con una ρ uniforme
#: para todos los pares, un límite por sector (``max_per_group``) no se puede
#: distinguir de un límite de heat total, porque todas las posiciones serían
#: igual de redundantes entre sí. Con correlación alta adentro del grupo y baja
#: entre grupos, el límite por grupo tiene algo que hacer.
GRUPOS: dict[str, list[str]] = {
    "mercado": ["SPY"],
    "tech": ["AAPL", "MSFT", "QQQ"],
    "energia": ["XOM", "CVX"],
    "defensivo": ["JNJ", "PG"],
}

#: parámetros individuales de cada símbolo del universo correlacionado
CORRELATED_UNIVERSE: dict[str, dict] = {
    "SPY": {"start_price": 260.0, "drift": 0.00040, "volatility": 0.010},
    "AAPL": {"start_price": 120.0, "drift": 0.00060, "volatility": 0.016},
    "MSFT": {"start_price": 180.0, "drift": 0.00050, "volatility": 0.014},
    "QQQ": {"start_price": 150.0, "drift": 0.00050, "volatility": 0.013},
    "XOM": {"start_price": 65.0, "drift": 0.00025, "volatility": 0.015},
    "CVX": {"start_price": 95.0, "drift": 0.00028, "volatility": 0.014},
    "JNJ": {"start_price": 140.0, "drift": 0.00030, "volatility": 0.009},
    "PG": {"start_price": 110.0, "drift": 0.00030, "volatility": 0.008},
}

#: correlación entre símbolos del mismo grupo (SPY-QQQ real ~0.92, AAPL-MSFT ~0.70)
RHO_INTRA = 0.85
#: correlación entre grupos distintos (tech-energía real ~0.30-0.45)
RHO_INTER = 0.35
#: el índice se mueve con todo: es la suma de los grupos (SPY-AAPL real ~0.75)
RHO_MERCADO = 0.70


def grupo_de(symbol: str) -> str:
    for grupo, symbols in GRUPOS.items():
        if symbol in symbols:
            return grupo
    return "otros"


def correlation_matrix(
    symbols: list[str],
    *,
    rho_intra: float = RHO_INTRA,
    rho_inter: float = RHO_INTER,
    rho_mercado: float = RHO_MERCADO,
) -> pd.DataFrame:
    """Matriz de correlación por pares, según la estructura de grupos."""
    n = len(symbols)
    matriz = np.eye(n)
    for i, a in enumerate(symbols):
        for j, b in enumerate(symbols):
            if i >= j:
                continue
            ga, gb = grupo_de(a), grupo_de(b)
            if "mercado" in (ga, gb):
                rho = rho_mercado
            elif ga == gb:
                rho = rho_intra
            else:
                rho = rho_inter
            matriz[i, j] = matriz[j, i] = rho
    return pd.DataFrame(matriz, index=symbols, columns=symbols)


def _cholesky(matriz: pd.DataFrame) -> np.ndarray:
    """Factor de Cholesky, con un mensaje claro si la matriz no es válida."""
    try:
        return np.linalg.cholesky(matriz.to_numpy())
    except np.linalg.LinAlgError as exc:
        autovalores = np.linalg.eigvalsh(matriz.to_numpy())
        raise ValueError(
            "la matriz de correlación pedida no es definida positiva "
            f"(autovalor mínimo {autovalores.min():.4f}): no existe ningún conjunto "
            "de series con esas correlaciones entre sí"
        ) from exc


def correlated_universe(
    specs: dict[str, dict] | None = None,
    *,
    corr: float | pd.DataFrame | None = None,
    bars: int = DEFAULT_BARS,
    start: str = "2018-01-01",
    seed: int = 101,
    gap_corr: float | pd.DataFrame | None = None,
    gap_volatility: float = 0.003,
    base_volume: int = 2_000_000,
) -> dict[str, pd.DataFrame]:
    """Series OHLCV con correlación controlada entre sus retornos diarios.

    Modelo: se sortean shocks normales estándar independientes y se los mezcla
    con el factor de Cholesky de la matriz pedida, así que la correlación de los
    retornos es **exactamente** la que se pide (salvo error muestral). Cada
    símbolo mantiene su drift y su volatilidad::

        z = Z · Lᵀ                       (Z normales iid, L = chol(C))
        r_i(t) = drift_i + vol_i · z_i(t)

    ``corr`` acepta un escalar (misma ρ para todos los pares) o una matriz
    completa; por defecto usa la estructura de grupos de ``GRUPOS``.

    ``gap_corr`` controla la correlación de los **gaps de apertura**, que es lo
    que decide si varios stops saltan la misma mañana. Por defecto usa la misma
    matriz que los retornos: en el mercado real los huecos se abren juntos.
    """
    specs = specs or CORRELATED_UNIVERSE
    symbols = list(specs)
    n = len(symbols)

    if corr is None:
        matriz = correlation_matrix(symbols)
    elif isinstance(corr, (int, float)):
        matriz = pd.DataFrame(
            np.full((n, n), float(corr)) + np.eye(n) * (1.0 - float(corr)),
            index=symbols,
            columns=symbols,
        )
    else:
        matriz = corr.loc[symbols, symbols]

    if gap_corr is None:
        gap_matriz = matriz
    elif isinstance(gap_corr, (int, float)):
        gap_matriz = pd.DataFrame(
            np.full((n, n), float(gap_corr)) + np.eye(n) * (1.0 - float(gap_corr)),
            index=symbols,
            columns=symbols,
        )
    else:
        gap_matriz = gap_corr.loc[symbols, symbols]

    chol, chol_gaps = _cholesky(matriz), _cholesky(gap_matriz)

    rng = np.random.default_rng(seed)
    index = pd.bdate_range(start=start, periods=bars, name="date")
    z = rng.normal(size=(bars, n)) @ chol.T
    z_gaps = rng.normal(size=(bars, n)) @ chol_gaps.T

    out: dict[str, pd.DataFrame] = {}
    for i, symbol in enumerate(symbols):
        params = specs[symbol]
        volatility = params.get("volatility", 0.012)
        shocks = params.get("drift", 0.0004) + volatility * z[:, i]
        gaps = gap_volatility * z_gaps[:, i]
        out[symbol] = _ohlcv_from_shocks(
            shocks,
            gaps,
            rng=rng,
            index=index,
            start_price=params.get("start_price", 100.0),
            volatility=volatility,
            base_volume=base_volume,
        )
    return out
