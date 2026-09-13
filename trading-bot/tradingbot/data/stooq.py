"""Proveedor Stooq: fallback gratuito de EOD diario, sin API key.

Cuidado: Stooq ajusta por splits pero **no por dividendos**, así que sus series
no son comparables con las de Yahoo. Sirve para que el `scan` no se caiga un día
que Yahoo falla, no para mezclar proveedores dentro de un mismo backtest — el
cache guarda de qué proveedor vino cada serie y se niega a mezclar.
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from tradingbot.data.provider import Provider
from tradingbot.data.validate import DataValidationError, EmptySeriesError, validate_ohlcv

STOOQ_URL = "https://stooq.com/q/d/l/"


class StooqProvider(Provider):
    name = "stooq"
    adjusted = False  # solo splits, no dividendos

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def get_ohlcv(
        self,
        symbol: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if interval != "1d":
            raise ValueError("Stooq solo se usa para velas diarias (interval='1d')")

        params = {"s": f"{symbol.lower()}.us", "i": "d"}
        resp = requests.get(STOOQ_URL, params=params, timeout=self.timeout)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or text.lower().startswith("no data"):
            # respuesta vacía: puede ser throttle, así que es reintentable
            raise EmptySeriesError(f"{symbol}: Stooq devolvió una serie vacía")

        raw = pd.read_csv(io.StringIO(text))
        df = validate_ohlcv(raw, symbol)
        if start is not None:
            df = df[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end)]
        if df.empty:
            raise DataValidationError(f"{symbol}: Stooq no tiene velas en el rango pedido")
        return df
