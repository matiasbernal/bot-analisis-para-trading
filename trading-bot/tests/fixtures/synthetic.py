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
    closes = start_price * np.exp(np.cumsum(shocks))

    gaps = rng.normal(0.0, gap_volatility, size=bars)
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
    """Las series sintéticas del universo, por símbolo."""
    chosen = symbols or list(SYNTHETIC_UNIVERSE)
    out: dict[str, pd.DataFrame] = {}
    for symbol in chosen:
        params = SYNTHETIC_UNIVERSE.get(symbol, {"seed": abs(hash(symbol)) % 10_000})
        out[symbol] = synthetic_ohlcv(bars=bars, start=start, **params)
    return out
