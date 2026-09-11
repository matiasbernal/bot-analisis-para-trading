"""Velas escritas a mano para cada caso de salida.

Cuando un test falla sobre datos generados, lo primero que hay que averiguar es
si el dato era el que se creía. Con velas a mano no hay dudas.
"""

from __future__ import annotations

import pandas as pd

Bar = tuple[float, float, float, float]  # open, high, low, close


def frame(bars: list[Bar], *, start: str = "2020-01-01", volume: int = 1_000_000) -> pd.DataFrame:
    """OHLCV a partir de una lista de velas ``(open, high, low, close)``."""
    index = pd.bdate_range(start=start, periods=len(bars), name="date")
    return pd.DataFrame(
        {
            "open": [b[0] for b in bars],
            "high": [b[1] for b in bars],
            "low": [b[2] for b in bars],
            "close": [b[3] for b in bars],
            "volume": [volume] * len(bars),
        },
        index=index,
        dtype="float64",
    ).astype({"volume": "int64"})


def flat(n: int, price: float = 100.0) -> list[Bar]:
    """``n`` velas planas: sirven de relleno para el warmup de los indicadores."""
    return [(price, price * 1.005, price * 0.995, price)] * n
