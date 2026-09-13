"""Proveedor de CSV locales: fixtures y datos exportados a mano.

Es el proveedor que usan los tests y el backtest del sandbox, donde no hay red.
Busca ``<root>/<SIMBOLO>.csv`` y, si no está, ``<root>/synthetic/<SIMBOLO>.csv``:
lo que está en la raíz tiene precedencia sobre lo sintético.

Esa precedencia es la razón por la que los fixtures reales viven en
``tests/fixtures/real/`` y se piden apuntando el ``root`` ahí, en vez de quedar
sueltos en ``tests/fixtures/``: si estuvieran sueltos, un ``SPY.csv`` real le
pisaría el sintético al universo "independiente (4)" de `poder.py` y
`universo.py` y ese universo pasaría a ser mitad real y mitad sintético sin que
nada avise. `tests/test_fixtures_reales.py` falla si eso vuelve a ser posible.
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
        # `encoding` explícito y no el default de pandas: los fixtures se
        # commitean en UTF-8 y se leen igual en las tres plataformas
        raw = pd.read_csv(self.path_for(symbol), encoding="utf-8")
        df = validate_ohlcv(raw, symbol)
        if start is not None:
            df = df[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end)]
        if df.empty:
            raise DataValidationError(f"{symbol}: el CSV no tiene velas en el rango pedido")
        return df
