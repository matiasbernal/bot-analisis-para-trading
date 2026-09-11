"""Interfaz abstracta de proveedor de datos.

Contrato de salida (ver PLAN.md, "Contratos entre capas"): un DataFrame con
índice DatetimeIndex tz-naive llamado ``date``, ordenado, sin duplicados,
columnas ``open high low close volume`` (float64 salvo ``volume`` int64),
ajustado por splits y dividendos, sin NaN.

Cada implementación devuelve lo que puede; ``data.validate.validate_ohlcv`` es
el único lugar donde se normaliza y se garantiza el contrato.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


class Provider(ABC):
    """Fuente de velas OHLCV."""

    #: nombre corto del proveedor; el cache lo guarda y el motor se niega a mezclar
    name: str = "abstract"

    #: True si la serie viene ajustada por splits **y** dividendos
    adjusted: bool = True

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Devuelve el OHLCV de ``symbol`` ya validado y normalizado."""
        raise NotImplementedError
