"""Cache local en parquet con descarga incremental.

Dos cosas que hacen falta y que un cache ingenuo no hace:

* **Los precios ajustados cambian retroactivamente** en cada dividendo o split.
  Un cache que solo agrega barras al final queda inconsistente. Al refrescar se
  bajan las últimas ``OVERLAP_BARS`` velas y se comparan con el cache; si
  difieren más de ``TOLERANCE`` relativo, se rebaja el histórico completo.
* **No se mezclan proveedores.** Un sidecar JSON guarda ``provider``,
  ``fetched_at`` y ``adjusted``; pedir una serie de Yahoo sobre un cache de
  Stooq falla en vez de devolver una mezcla silenciosa.

Si el proveedor se cae, los backtests siguen corriendo sobre el cache
(``refresh=False`` o ``offline=True``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from tradingbot.data.provider import OHLCV_COLUMNS, Provider
from tradingbot.data.validate import DataValidationError, validate_ohlcv

#: velas que se rebajan y comparan en cada refresco para detectar reajustes
OVERLAP_BARS = 30

#: diferencia relativa a partir de la cual se considera que el ajuste cambió
TOLERANCE = 1e-6


class CacheConsistencyError(DataValidationError):
    """El solape entre cache y proveedor no coincide: hubo reajuste de precios."""


@dataclass(frozen=True)
class CacheMeta:
    provider: str
    interval: str
    adjusted: bool
    rows: int
    first: str
    last: str
    fetched_at: str


class ParquetCache:
    """Guarda series OHLCV en ``root/<interval>/<SIMBOLO>.parquet``."""

    def __init__(self, root: str | Path, provider: Provider | None = None) -> None:
        self.root = Path(root)
        self.provider = provider

    # -- rutas -------------------------------------------------------------
    def _dir(self, interval: str) -> Path:
        return self.root / interval

    def path_for(self, symbol: str, interval: str = "1d") -> Path:
        return self._dir(interval) / f"{symbol.upper()}.parquet"

    def meta_path_for(self, symbol: str, interval: str = "1d") -> Path:
        return self._dir(interval) / f"{symbol.upper()}.json"

    # -- lectura / escritura ----------------------------------------------
    def read(self, symbol: str, interval: str = "1d") -> pd.DataFrame | None:
        path = self.path_for(symbol, interval)
        if not path.is_file():
            return None
        df = pd.read_parquet(path)
        return validate_ohlcv(df, symbol, check_calendar=False)

    def read_meta(self, symbol: str, interval: str = "1d") -> CacheMeta | None:
        path = self.meta_path_for(symbol, interval)
        if not path.is_file():
            return None
        return CacheMeta(**json.loads(path.read_text(encoding="utf-8")))

    def write(
        self,
        symbol: str,
        df: pd.DataFrame,
        *,
        provider: str,
        adjusted: bool,
        interval: str = "1d",
    ) -> Path:
        df = validate_ohlcv(df, symbol, check_calendar=False)
        directory = self._dir(interval)
        directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(symbol, interval)
        df.to_parquet(path)
        meta = CacheMeta(
            provider=provider,
            interval=interval,
            adjusted=adjusted,
            rows=len(df),
            first=df.index[0].strftime("%Y-%m-%d"),
            last=df.index[-1].strftime("%Y-%m-%d"),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self.meta_path_for(symbol, interval).write_text(
            json.dumps(asdict(meta), indent=2, sort_keys=True), encoding="utf-8"
        )
        return path

    # -- API principal -----------------------------------------------------
    def get(
        self,
        symbol: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        interval: str = "1d",
        *,
        refresh: bool = True,
        offline: bool = False,
    ) -> pd.DataFrame:
        """Devuelve el OHLCV del símbolo, usando el cache y bajando lo que falte."""
        cached = self.read(symbol, interval)
        meta = self.read_meta(symbol, interval)

        if cached is not None and meta is not None and self.provider is not None:
            if meta.provider != self.provider.name:
                raise CacheConsistencyError(
                    f"{symbol}: el cache viene de '{meta.provider}' y se pidió "
                    f"'{self.provider.name}'. No se mezclan proveedores en un backtest; "
                    "borrá el cache del símbolo si querés cambiar de fuente."
                )

        if offline or self.provider is None or (cached is not None and not refresh):
            if cached is None:
                raise DataValidationError(
                    f"{symbol}: no hay cache local y no se puede descargar "
                    f"(offline={offline}, provider={self.provider})"
                )
            return _slice(cached, start, end, symbol)

        if cached is None:
            fresh = self.provider.get_ohlcv(symbol, start=start, end=end, interval=interval)
            self.write(
                symbol,
                fresh,
                provider=self.provider.name,
                adjusted=self.provider.adjusted,
                interval=interval,
            )
            return _slice(fresh, start, end, symbol)

        return _slice(
            self._refresh(symbol, cached, start=start, end=end, interval=interval),
            start,
            end,
            symbol,
        )

    def _refresh(
        self,
        symbol: str,
        cached: pd.DataFrame,
        *,
        start,
        end,
        interval: str,
    ) -> pd.DataFrame:
        assert self.provider is not None
        overlap_start = cached.index[max(0, len(cached) - OVERLAP_BARS)]
        recent = self.provider.get_ohlcv(symbol, start=overlap_start, end=end, interval=interval)

        if self.overlap_differs(cached, recent):
            # hubo dividendo o split: la serie vieja quedó desajustada, se rebaja entera
            full = self.provider.get_ohlcv(symbol, start=start, end=end, interval=interval)
            self.write(
                symbol,
                full,
                provider=self.provider.name,
                adjusted=self.provider.adjusted,
                interval=interval,
            )
            return full

        merged = pd.concat([cached, recent[~recent.index.isin(cached.index)]]).sort_index()
        if len(merged) != len(cached):
            self.write(
                symbol,
                merged,
                provider=self.provider.name,
                adjusted=self.provider.adjusted,
                interval=interval,
            )
        return merged

    @staticmethod
    def overlap_differs(cached: pd.DataFrame, fresh: pd.DataFrame) -> bool:
        """True si el solape cache/proveedor difiere más de ``TOLERANCE`` relativo."""
        common = cached.index.intersection(fresh.index)
        if len(common) == 0:
            return False
        left = cached.loc[common, list(OHLCV_COLUMNS)].astype("float64")
        right = fresh.loc[common, list(OHLCV_COLUMNS)].astype("float64")
        denom = left.abs().where(left.abs() > 0, 1.0)
        return bool((((left - right).abs() / denom) > TOLERANCE).any().any())


def _slice(df: pd.DataFrame, start, end, symbol: str) -> pd.DataFrame:
    out = df
    if start is not None:
        out = out[out.index >= pd.Timestamp(start)]
    if end is not None:
        out = out[out.index <= pd.Timestamp(end)]
    if out.empty:
        raise DataValidationError(f"{symbol}: no hay velas en el rango pedido")
    return out


def frame_hash(df: pd.DataFrame) -> str:
    """Hash estable del contenido de una serie OHLCV (para el manifiesto)."""
    digest = hashlib.sha256()
    digest.update(df.index.strftime("%Y-%m-%d").str.cat(sep="|").encode("utf-8"))
    for col in OHLCV_COLUMNS:
        values = df[col].to_numpy(dtype="float64")
        digest.update(values.tobytes())
    return digest.hexdigest()


def dataset_hash(frames: dict[str, pd.DataFrame]) -> str:
    """Hash de un conjunto de series, independiente del orden del diccionario."""
    digest = hashlib.sha256()
    for symbol in sorted(frames):
        digest.update(symbol.encode("utf-8"))
        digest.update(frame_hash(frames[symbol]).encode("utf-8"))
    return digest.hexdigest()
