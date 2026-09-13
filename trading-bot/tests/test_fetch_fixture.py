"""Tests de ``scripts/fetch_fixture.py``, el bajador de fixtures reales.

Ninguno toca la red: el proveedor es falso y devuelve series deterministas. Lo
que se verifica es lo que el PLAN pide del bajador y no del proveedor — que la
descarga sea secuencial y espaciada, que el refresco detecte el reajuste
retroactivo de precios en vez de pegar barras nuevas sobre una serie vieja, que
cada CSV quede con su sidecar, y que una serie vacía sea un error y no un
archivo escrito a medias.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from tradingbot.data.provider import Provider
from tradingbot.data.validate import DataValidationError, EmptySeriesError

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fetch_fixture  # noqa: E402


#: la rampa de precios se ancla acá y no en el ``start`` pedido: pedir un tramo
#: tiene que devolver exactamente los mismos precios que pedir la serie entera,
#: como hace un proveedor de verdad. Si no, todo refresco parecería un reajuste.
ANCLA = pd.Timestamp("2000-01-03")


def serie(start: str, end: str, *, base: float = 100.0, factor: float = 1.0) -> pd.DataFrame:
    """Velas diarias deterministas en días hábiles. ``factor`` simula el reajuste."""
    fechas = pd.bdate_range(start=start, end=end, name="date")
    desde_el_ancla = pd.bdate_range(start=ANCLA, end=end).get_indexer(fechas)
    cierres = pd.Series(base + 0.1 * desde_el_ancla, index=fechas) * factor
    return pd.DataFrame(
        {
            "open": cierres * 0.995,
            "high": cierres * 1.01,
            "low": cierres * 0.99,
            "close": cierres,
            "volume": pd.Series(1_000_000, index=fechas, dtype="int64"),
        }
    )


class ProveedorFalso(Provider):
    """Devuelve la serie pedida y anota cada llamada. Sin red."""

    name = "falso"
    adjusted = True

    def __init__(
        self,
        *,
        factor: float = 1.0,
        vacios: tuple[str, ...] = (),
        fallas: int = 0,
        rotos: tuple[str, ...] = (),
        caidos: tuple[str, ...] = (),
    ):
        self.factor = factor
        self.vacios = vacios
        self.fallas_restantes = fallas
        self.rotos = rotos  # la serie llega entera pero no cumple el contrato
        self.caidos = caidos  # la red se corta antes de que llegue nada
        self.llamadas: list[tuple[str, str, str]] = []

    def get_ohlcv(self, symbol, start=None, end=None, interval="1d"):
        self.llamadas.append((symbol, str(start)[:10], str(end)[:10]))
        if self.fallas_restantes:
            self.fallas_restantes -= 1
            raise EmptySeriesError(f"{symbol}: el proveedor devolvió 0 velas")
        if symbol in self.vacios:
            raise EmptySeriesError(f"{symbol}: el proveedor devolvió 0 velas")
        if symbol in self.caidos:
            raise ConnectionError(f"{symbol}: la conexión se cortó")
        if symbol in self.rotos:
            raise DataValidationError(
                f"{symbol}: 3 velas con high < low, p.ej. 2018-01-19, 2019-03-04, 2020-11-12"
            )
        return serie(start, end, factor=self.factor)


@pytest.fixture
def sin_dormir():
    """Descarta las pausas para que los tests no tarden lo que tarda una descarga."""
    dormidas: list[float] = []
    return dormidas, dormidas.append


# --- N símbolos, 15 años, rate limit --------------------------------------
def test_baja_n_simbolos_secuencial_y_espaciado(tmp_path, sin_dormir):
    dormidas, dormir = sin_dormir
    provider = ProveedorFalso()
    simbolos = ["XLK", "XLF", "XLE", "SPY"]

    fallaron = fetch_fixture.bajar_universo(
        provider, simbolos, tmp_path, start="2010-01-01", end="2025-01-01", dormir=dormir
    )

    assert fallaron == 0
    assert [s for s, _, _ in provider.llamadas] == simbolos  # uno por vez, en orden
    assert dormidas == [fetch_fixture.PAUSA_DEFAULT] * (len(simbolos) - 1)
    assert sorted(p.name for p in tmp_path.glob("*.csv")) == ["SPY.csv", "XLE.csv", "XLF.csv", "XLK.csv"]


def test_quince_anios_llegan_enteros_al_proveedor(tmp_path, sin_dormir):
    _, dormir = sin_dormir
    provider = ProveedorFalso()

    fetch_fixture.bajar_universo(
        provider, ["SPY"], tmp_path, start="2010-01-01", end="2025-12-31", dormir=dormir
    )

    assert provider.llamadas == [("SPY", "2010-01-01", "2025-12-31")]
    guardado = pd.read_csv(tmp_path / "SPY.csv", parse_dates=["date"])
    assert guardado["date"].iloc[0].year == 2010 and guardado["date"].iloc[-1].year == 2025
    assert len(guardado) > 3_000  # ~252 velas por año


def test_main_traduce_years_a_una_ventana_de_quince_anios(tmp_path, monkeypatch):
    """``--years 15`` tiene que pedir quince años, no los tres del default."""
    provider = ProveedorFalso()
    monkeypatch.setattr("tradingbot.data.yahoo.YahooProvider", lambda: provider)
    monkeypatch.setattr(fetch_fixture.time, "sleep", lambda _: None)

    codigo = fetch_fixture.main(
        ["SPY", "QQQ", "--years", "15", "--end", "2025-12-31", "--out", str(tmp_path)]
    )

    assert codigo == 0
    assert [s for s, _, _ in provider.llamadas] == ["SPY", "QQQ"]
    inicio = pd.Timestamp(provider.llamadas[0][1])
    assert 15.0 <= (pd.Timestamp("2025-12-31") - inicio).days / 365.25 <= 15.1


# --- reajuste retroactivo -------------------------------------------------
def test_refresco_sin_reajuste_pega_solo_las_velas_nuevas(tmp_path, sin_dormir):
    _, dormir = sin_dormir
    provider = ProveedorFalso()
    fetch_fixture.bajar_universo(
        provider, ["SPY"], tmp_path, start="2020-01-01", end="2020-06-30", dormir=dormir
    )
    primero = pd.read_csv(tmp_path / "SPY.csv")

    fetch_fixture.bajar_universo(
        provider, ["SPY"], tmp_path, start="2020-01-01", end="2020-07-31", dormir=dormir
    )
    segundo = pd.read_csv(tmp_path / "SPY.csv")

    # la segunda corrida pide solo el solape, no los seis meses otra vez
    assert provider.llamadas[1][1] > "2020-05-01"
    assert len(provider.llamadas) == 2
    assert len(segundo) > len(primero)
    assert segundo["close"].iloc[0] == pytest.approx(primero["close"].iloc[0])


def test_refresco_con_reajuste_rebaja_el_historico_entero(tmp_path, sin_dormir):
    """Un dividendo cambia los precios hacia atrás: la serie vieja no sirve más."""
    _, dormir = sin_dormir
    provider = ProveedorFalso()
    fetch_fixture.bajar_universo(
        provider, ["SPY"], tmp_path, start="2020-01-01", end="2020-06-30", dormir=dormir
    )
    viejo = pd.read_csv(tmp_path / "SPY.csv")

    provider.factor = 0.98  # Yahoo reajustó todo un 2% hacia abajo
    fetch_fixture.bajar_universo(
        provider, ["SPY"], tmp_path, start="2020-01-01", end="2020-06-30", dormir=dormir
    )
    nuevo = pd.read_csv(tmp_path / "SPY.csv")

    # tres llamadas: completa, solape (difiere) y completa otra vez
    assert len(provider.llamadas) == 3
    assert provider.llamadas[2][1] == "2020-01-01"
    assert len(nuevo) == len(viejo)
    assert nuevo["close"].iloc[0] == pytest.approx(viejo["close"].iloc[0] * 0.98)
    assert nuevo["close"].iloc[-1] == pytest.approx(viejo["close"].iloc[-1] * 0.98)


def test_una_diferencia_menor_a_la_tolerancia_no_rebaja(tmp_path, sin_dormir):
    """1e-9 relativo es ruido de punto flotante, no un reajuste."""
    _, dormir = sin_dormir
    provider = ProveedorFalso()
    fetch_fixture.bajar_universo(
        provider, ["SPY"], tmp_path, start="2020-01-01", end="2020-06-30", dormir=dormir
    )

    provider.factor = 1 + 1e-9
    fetch_fixture.bajar_universo(
        provider, ["SPY"], tmp_path, start="2020-01-01", end="2020-06-30", dormir=dormir
    )

    assert len(provider.llamadas) == 2  # completa + solape, sin rebaja


# --- sidecar --------------------------------------------------------------
def test_cada_csv_queda_con_su_sidecar(tmp_path, sin_dormir):
    _, dormir = sin_dormir
    provider = ProveedorFalso()

    fetch_fixture.bajar_universo(
        provider, ["SPY"], tmp_path, start="2020-01-01", end="2020-06-30", dormir=dormir
    )

    meta = json.loads((tmp_path / "SPY.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "falso"
    assert meta["adjusted"] is True
    assert meta["interval"] == "1d"
    assert meta["first"] == "2020-01-01" and meta["last"] <= "2020-06-30"
    assert meta["rows"] == len(pd.read_csv(tmp_path / "SPY.csv"))
    assert meta["fetched_at"].startswith("20") and meta["fetched_at"].endswith("+00:00")


def test_el_sidecar_dice_que_stooq_no_ajusta_por_dividendos(tmp_path, sin_dormir):
    """Yahoo y Stooq no son comparables y el sidecar es donde eso queda escrito."""
    _, dormir = sin_dormir
    provider = ProveedorFalso()
    provider.name, provider.adjusted = "stooq", False

    fetch_fixture.bajar_universo(
        provider, ["SPY"], tmp_path, start="2020-01-01", end="2020-06-30", dormir=dormir
    )

    meta = json.loads((tmp_path / "SPY.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "stooq" and meta["adjusted"] is False


# --- vacío = error --------------------------------------------------------
def test_serie_vacia_es_error_y_no_escribe_nada(tmp_path, sin_dormir):
    _, dormir = sin_dormir
    provider = ProveedorFalso(vacios=("ZZZZ",))

    fallaron = fetch_fixture.bajar_universo(
        provider, ["ZZZZ"], tmp_path, start="2020-01-01", end="2020-06-30",
        dormir=dormir, reintentos=1,
    )

    assert fallaron == 1
    assert not (tmp_path / "ZZZZ.csv").exists()
    assert not (tmp_path / "ZZZZ.json").exists()


def test_un_simbolo_vacio_no_frena_a_los_otros_pero_el_codigo_de_salida_lo_dice(
    tmp_path, sin_dormir
):
    _, dormir = sin_dormir
    provider = ProveedorFalso(vacios=("ZZZZ",))

    fallaron = fetch_fixture.bajar_universo(
        provider, ["SPY", "ZZZZ", "QQQ"], tmp_path, start="2020-01-01", end="2020-06-30",
        dormir=dormir, reintentos=1,
    )

    assert fallaron == 1
    assert (tmp_path / "SPY.csv").exists() and (tmp_path / "QQQ.csv").exists()
    assert not (tmp_path / "ZZZZ.csv").exists()


def test_un_csv_vacio_no_pisa_al_que_ya_estaba(tmp_path, sin_dormir):
    """Si el refresco falla, el fixture viejo sigue siendo el fixture."""
    _, dormir = sin_dormir
    bueno = ProveedorFalso()
    fetch_fixture.bajar_universo(
        bueno, ["SPY"], tmp_path, start="2020-01-01", end="2020-06-30", dormir=dormir
    )
    antes = (tmp_path / "SPY.csv").read_text(encoding="utf-8")

    roto = ProveedorFalso(vacios=("SPY",))
    fallaron = fetch_fixture.bajar_universo(
        roto, ["SPY"], tmp_path, start="2020-01-01", end="2020-07-31",
        dormir=dormir, reintentos=1,
    )

    assert fallaron == 1
    assert (tmp_path / "SPY.csv").read_text(encoding="utf-8") == antes


# --- reintentos -----------------------------------------------------------
def test_el_429_se_reintenta_con_espera_que_se_duplica(monkeypatch):
    """El límite de tasa de Yahoo llega como serie vacía; dos intentos y sale."""
    esperas: list[float] = []
    monkeypatch.setattr(fetch_fixture.time, "sleep", esperas.append)
    provider = ProveedorFalso(fallas=2)

    df = fetch_fixture.con_reintentos(
        lambda: provider.get_ohlcv("SPY", start="2020-01-01", end="2020-06-30"),
        reintentos=3,
        aviso=lambda _: None,
    )

    assert len(df) > 100
    assert esperas == [fetch_fixture.ESPERA_INICIAL, fetch_fixture.ESPERA_INICIAL * 2]


def test_agotados_los_reintentos_el_error_queda_en_pie(monkeypatch):
    monkeypatch.setattr(fetch_fixture.time, "sleep", lambda _: None)
    provider = ProveedorFalso(fallas=99)

    with pytest.raises(DataValidationError, match="0 velas"):
        fetch_fixture.con_reintentos(
            lambda: provider.get_ohlcv("SPY", start="2020-01-01", end="2020-06-30"),
            reintentos=3,
            aviso=lambda _: None,
        )


def test_un_corte_de_red_se_reintenta(monkeypatch):
    """Red caída: transitorio, aunque no sea `EmptySeriesError`."""
    esperas: list[float] = []
    monkeypatch.setattr(fetch_fixture.time, "sleep", esperas.append)
    provider = ProveedorFalso(caidos=("SPY",))

    with pytest.raises(ConnectionError):
        fetch_fixture.con_reintentos(
            lambda: provider.get_ohlcv("SPY", start="2020-01-01", end="2020-06-30"),
            reintentos=3,
            aviso=lambda _: None,
        )

    assert len(provider.llamadas) == 3
    assert esperas == [fetch_fixture.ESPERA_INICIAL, fetch_fixture.ESPERA_INICIAL * 2]


# --- transitorio vs permanente --------------------------------------------
def test_una_falla_de_validacion_no_se_reintenta(monkeypatch):
    """Es determinística: los tres intentos bajan los mismos bytes y los rechazan.

    Antes perdía 6 segundos de backoff (2s + 4s) para llegar al mismo error.
    """
    esperas: list[float] = []
    monkeypatch.setattr(fetch_fixture.time, "sleep", esperas.append)
    provider = ProveedorFalso(rotos=("SPY",))

    with pytest.raises(DataValidationError, match="high < low"):
        fetch_fixture.con_reintentos(
            lambda: provider.get_ohlcv("SPY", start="2020-01-01", end="2020-06-30"),
            reintentos=3,
            aviso=lambda _: None,
        )

    assert len(provider.llamadas) == 1  # un intento, no tres
    assert esperas == []  # ni un segundo de backoff


def test_que_es_transitorio_y_que_no():
    """La regla, sin pasar por el bajador."""
    assert fetch_fixture.es_transitorio(EmptySeriesError("SPY: 0 velas"))  # el 429 de Yahoo
    assert fetch_fixture.es_transitorio(ConnectionError("connection reset"))
    assert fetch_fixture.es_transitorio(TimeoutError("read timeout"))
    assert not fetch_fixture.es_transitorio(DataValidationError("SPY: 3 velas con high < low"))
    assert not fetch_fixture.es_transitorio(DataValidationError("SPY: hay volumen negativo"))


def test_un_simbolo_roto_falla_una_sola_vez_y_no_frena_a_los_otros(tmp_path, sin_dormir):
    _, dormir = sin_dormir
    provider = ProveedorFalso(rotos=("XLE",))

    fallaron = fetch_fixture.bajar_universo(
        provider, ["SPY", "XLE", "QQQ"], tmp_path, start="2020-01-01", end="2020-06-30",
        dormir=dormir,  # reintentos=3, el default
    )

    assert fallaron == 1
    assert [s for s, _, _ in provider.llamadas] == ["SPY", "XLE", "QQQ"]  # XLE una vez sola
    assert not (tmp_path / "XLE.csv").exists()
    assert (tmp_path / "SPY.csv").exists() and (tmp_path / "QQQ.csv").exists()
