"""Proveedor de CSV locales: fixtures y datos exportados a mano.

Es el proveedor que usan los tests y el backtest del sandbox, donde no hay red.
Busca ``<root>/<SIMBOLO>.csv`` y, si no está, ``<root>/synthetic/<SIMBOLO>.csv``:
los fixtures reales (generados con ``scripts/fetch_fixture.py``) tienen
precedencia sobre los sintéticos.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tradingbot.data.provider import Provider
from tradingbot.data.validate import DataValidationError, validate_ohlcv


class LocalCsvProvider(Provider):
    name = "local_csv"
    adjusted = True

    def __init__(self, root: str | Path, *, subdirs: tuple[str, ...] = ("synthetic",)) -> None:
        self.root = Path(root)
        self.subdirs = subdirs

    def path_for(self, symbol: str) -> Path:
        candidates = [self.root / f"{symbol.upper()}.csv"]
        candidates += [self.root / sub / f"{symbol.upper()}.csv" for sub in self.subdirs]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise DataValidationError(
            f"{symbol}: no hay CSV en {self.root} "
            f"(buscado: {', '.join(str(c) for c in candidates)})"
        )

    def has(self, symbol: str) -> bool:
        try:
            self.path_for(symbol)
        except DataValidationError:
            return False
        return True

    def get_ohlcv(
        self,
        symbol: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        raw = pd.read_csv(self.path_for(symbol))
        df = validate_ohlcv(raw, symbol)
        if start is not None:
            df = df[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end)]
        if df.empty:
            raise DataValidationError(f"{symbol}: el CSV no tiene velas en el rango pedido")
        return df
