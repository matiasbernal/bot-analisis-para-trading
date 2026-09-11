"""Fase 0: el cache en parquet escribe, lee, agrega, y detecta reajustes.

El caso que rompe a un cache ingenuo: los precios ajustados cambian
retroactivamente en cada dividendo o split. Si el solape con el proveedor no
coincide, hay que rebajar el histórico entero, no agregar barras al final.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fixtures.synthetic import synthetic_ohlcv

from tradingbot.data.cache import (
    CacheConsistencyError,
    ParquetCache,
    dataset_hash,
    frame_hash,
)
from tradingbot.data.local import LocalCsvProvider
from tradingbot.data.provider import Provider
from tradingbot.data.validate import DataValidationError, validate_ohlcv

SERIE = validate_ohlcv(synthetic_ohlcv(bars=300, seed=5), "FAKE")


class FakeProvider(Provider):
    """Proveedor de mentira: devuelve un tramo de una serie fija y cuenta llamadas."""

    name = "fake"
    adjusted = True

    def __init__(self, df: pd.DataFrame = SERIE) -> None:
        self.df = df
        self.calls: list[tuple] = []

    def get_ohlcv(self, symbol, start=None, end=None, interval="1d"):
        self.calls.append((symbol, start, end))
        out = self.df
        if start is not None:
            out = out[out.index >= pd.Timestamp(start)]
        if end is not None:
            out = out[out.index <= pd.Timestamp(end)]
        if out.empty:
            raise DataValidationError(f"{symbol}: vacío")
        return out


def test_escribe_y_lee(tmp_path):
    cache = ParquetCache(tmp_path, FakeProvider())
    df = cache.get("FAKE")
    assert len(df) == len(SERIE)
    assert cache.path_for("FAKE").is_file()

    meta = cache.read_meta("FAKE")
    assert meta.provider == "fake" and meta.adjusted is True
    assert meta.rows == len(SERIE)
    assert pd.read_parquet(cache.path_for("FAKE")).equals(df)


def test_segunda_corrida_no_rebaja_todo(tmp_path):
    provider = FakeProvider()
    cache = ParquetCache(tmp_path, provider)
    cache.get("FAKE")
    llamadas_iniciales = len(provider.calls)

    cache.get("FAKE")
    # solo se pide el solape (las últimas barras), no la serie entera
    assert len(provider.calls) == llamadas_iniciales + 1
    _, start, _ = provider.calls[-1]
    assert start == SERIE.index[-30]


def test_descarga_incremental_agrega_barras_nuevas(tmp_path):
    parcial = SERIE.iloc[:-10]
    cache = ParquetCache(tmp_path, FakeProvider(parcial))
    cache.get("FAKE")
    assert len(cache.read("FAKE")) == len(parcial)

    cache.provider = FakeProvider(SERIE)  # ahora el proveedor tiene 10 velas más
    df = cache.get("FAKE")
    assert len(df) == len(SERIE)
    assert len(cache.read("FAKE")) == len(SERIE)


def test_detecta_reajuste_en_el_solape_y_rebaja_todo(tmp_path):
    cache = ParquetCache(tmp_path, FakeProvider())
    cache.get("FAKE")

    reajustada = SERIE * 1.0
    for col in ("open", "high", "low", "close"):
        reajustada[col] = reajustada[col] * 0.97  # dividendo: se reajusta el histórico
    reajustada["volume"] = SERIE["volume"]

    assert ParquetCache.overlap_differs(SERIE, reajustada)

    cache.provider = FakeProvider(reajustada)
    df = cache.get("FAKE")
    assert df["close"].iloc[0] == pytest.approx(reajustada["close"].iloc[0])
    assert cache.read("FAKE")["close"].iloc[0] == pytest.approx(reajustada["close"].iloc[0])


def test_no_mezcla_proveedores(tmp_path):
    cache = ParquetCache(tmp_path, FakeProvider())
    cache.get("FAKE")

    class OtroProveedor(FakeProvider):
        name = "otro"

    cache.provider = OtroProveedor()
    with pytest.raises(CacheConsistencyError, match="No se mezclan proveedores"):
        cache.get("FAKE")


def test_modo_offline_usa_el_cache(tmp_path):
    """Si el proveedor se cae, los backtests siguen corriendo sobre el cache."""
    provider = FakeProvider()
    cache = ParquetCache(tmp_path, provider)
    cache.get("FAKE")
    llamadas = len(provider.calls)

    df = cache.get("FAKE", offline=True)
    assert len(df) == len(SERIE)
    assert len(provider.calls) == llamadas  # no se llamó al proveedor


def test_offline_sin_cache_falla_claro(tmp_path):
    cache = ParquetCache(tmp_path, FakeProvider())
    with pytest.raises(DataValidationError, match="no hay cache local"):
        cache.get("FAKE", offline=True)


def test_hash_de_datos_es_estable_y_sensible(tmp_path):
    otro = SERIE.copy()
    otro.iloc[0, otro.columns.get_loc("close")] += 0.01
    assert frame_hash(SERIE) == frame_hash(SERIE.copy())
    assert frame_hash(SERIE) != frame_hash(otro)
    assert dataset_hash({"A": SERIE, "B": otro}) == dataset_hash({"B": otro, "A": SERIE})


def test_provider_de_csv_locales_prefiere_el_real(tmp_path):
    (tmp_path / "synthetic").mkdir()
    SERIE.to_csv(tmp_path / "synthetic" / "SPY.csv", index_label="date")
    provider = LocalCsvProvider(tmp_path)
    assert provider.has("SPY")
    assert provider.path_for("SPY").parent.name == "synthetic"

    real = SERIE.iloc[:100]
    real.to_csv(tmp_path / "SPY.csv", index_label="date")
    assert provider.path_for("SPY").parent == tmp_path
    assert len(provider.get_ohlcv("SPY")) == 100


def test_provider_de_csv_locales_sin_archivo(tmp_path):
    with pytest.raises(DataValidationError, match="no hay CSV"):
        LocalCsvProvider(tmp_path).get_ohlcv("NOEXISTE")
