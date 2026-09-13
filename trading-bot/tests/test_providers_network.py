"""Tests que necesitan internet.

El sandbox donde se construyó esto no llega a Yahoo ni a Stooq (política de red
del entorno), así que estos tests detectan conectividad y se saltean con el
motivo. En tu máquina corren solos; son los que verifican que el contrato OHLCV
se cumple también con datos reales.
"""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import has_network, requires_network, requires_stooq, sondear

from tradingbot.data.cache import ParquetCache
from tradingbot.data.provider import OHLCV_COLUMNS


def test_el_detector_de_red_no_explota():
    assert isinstance(has_network(), bool)


@pytest.mark.parametrize(
    "respuesta, esperado, fragmento",
    [
        (200, True, "ok"),
        (429, False, "HTTP 429"),
        (403, False, "HTTP 403"),
        (None, False, "no se llega al host"),
    ],
)
def test_el_detector_distingue_host_bloqueado_de_proveedor_que_no_sirve(
    monkeypatch, respuesta, esperado, fragmento
):
    """Son dos fallas distintas y se arreglan en lugares distintos.

    Un 403 en el CONNECT es la política de red del entorno; un 429 del proveedor
    es Yahoo negándole datos a esta IP con el host permitido. Si el motivo del
    skip dice siempre "política de red", el segundo caso manda a revisar una
    configuración que ya está bien.
    """
    import requests

    def falso_get(url, timeout=None):
        if respuesta is None:
            raise requests.ConnectionError("boom")
        return type("R", (), {"status_code": respuesta})()

    monkeypatch.setattr(requests, "get", falso_get)
    sondear.cache_clear()
    try:
        alcanzable, motivo = sondear("https://ejemplo.invalido/ping")
    finally:
        sondear.cache_clear()

    assert alcanzable is esperado
    assert fragmento in motivo


@requires_network
@pytest.mark.network
def test_yahoo_devuelve_el_contrato():
    from tradingbot.data.yahoo import YahooProvider

    df = YahooProvider().get_ohlcv("SPY", start="2023-01-01", end="2023-06-30")
    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert df.index.tz is None and df.index.name == "date"
    assert len(df) > 100 and not df.isna().any().any()


@requires_stooq
@pytest.mark.network
def test_stooq_devuelve_el_contrato():
    from tradingbot.data.stooq import StooqProvider

    df = StooqProvider().get_ohlcv("SPY", start="2023-01-01", end="2023-06-30")
    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert len(df) > 100


@requires_network
@pytest.mark.network
def test_el_cache_sobrevive_a_que_se_caiga_el_proveedor(tmp_path):
    """Descargar, cortar internet, volver a correr: sale del cache."""
    from tradingbot.data.yahoo import YahooProvider

    cache = ParquetCache(tmp_path, YahooProvider())
    primera = cache.get("SPY", start="2022-01-01", end="2023-01-01")

    cache.provider = None  # el proveedor ya no existe
    segunda = cache.get("SPY", start="2022-01-01", end="2023-01-01", offline=True)
    assert len(primera) == len(segunda)
    assert primera["close"].iloc[-1] == pytest.approx(segunda["close"].iloc[-1])


@requires_network
@pytest.mark.network
def test_simbolo_inexistente_es_error_no_serie_vacia():
    from tradingbot.data.validate import DataValidationError
    from tradingbot.data.yahoo import YahooProvider

    with pytest.raises(DataValidationError):
        YahooProvider().get_ohlcv(
            "ZZZZNOEXISTE", start="2023-01-01", end=str(pd.Timestamp.today().date())
        )
