"""Proveedor Yahoo Finance vía yfinance.

Lo que muerde si no se contempla (ver PLAN.md): ``Ticker.history`` devuelve
columnas planas (``yf.download`` devuelve MultiIndex y es más frágil), el índice
viene tz-aware, trae ``Dividends``/``Stock Splits``, y devuelve un DataFrame
vacío **sin error** si el símbolo no existe o si te limitó la tasa.
"""

from __future__ import annotations

import time

import pandas as pd

from tradingbot.data.provider import Provider
from tradingbot.data.validate import DataValidationError, validate_ohlcv


class YahooProvider(Provider):
    name = "yahoo"
    adjusted = True

    def __init__(self, pause_seconds: float = 0.5) -> None:
        # descarga secuencial con pausa; nunca threads=True (rate limit)
        self.pause_seconds = pause_seconds
        self._last_call = 0.0

    def get_ohlcv(
        self,
        symbol: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "yfinance no está instalado; instalá el paquete o usá otro proveedor"
            ) from exc

        self._throttle()
        raw = yf.Ticker(symbol).history(
            start=start, end=end, interval=interval, auto_adjust=True
        )
        if raw is None or raw.empty:
            raise DataValidationError(
                f"{symbol}: Yahoo devolvió una serie vacía "
                "(símbolo inexistente o límite de tasa). Vacío = error, siempre."
            )
        return validate_ohlcv(raw, symbol)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if self._last_call and elapsed < self.pause_seconds:
            time.sleep(self.pause_seconds - elapsed)
        self._last_call = time.monotonic()
