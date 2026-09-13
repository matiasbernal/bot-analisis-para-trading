"""Tests sobre los CSV reales de ``tests/fixtures/real/``.

Esos archivos los genera el usuario en su máquina con
``python scripts/fetch_fixture.py --start 2010-01-01 --end 2025-12-31 SPY QQQ ...``
y se commitean. Hasta que existan, estos tests se saltean con el motivo; no
bloquean nada.

**Por qué viven en un subdirectorio y no sueltos en ``tests/fixtures/``.**
``LocalCsvProvider`` busca ``<root>/SYM.csv`` ANTES que
``<root>/synthetic/SYM.csv``. Un ``SPY.csv`` real en la raíz de
``tests/fixtures/`` le pisaría el sintético al universo "independiente (4)" de
`poder.py` y `universo.py`, que pasaría a ser mitad real y mitad sintético sin
que nada avise: los números de poder seguirían saliendo, pero medirían otra cosa.
El último test de este archivo falla si esa contaminación vuelve a ser posible.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from conftest import (
    FIXTURES_DIR,
    REAL_FIXTURES,
    REAL_FIXTURES_DIR,
    real_fixture_path,
    requires_real_fixture,
    sidecar_real,
)

from tradingbot.backtest.engine import run_backtest
from tradingbot.config import load_strategy
from tradingbot.data.local import LocalCsvProvider
from tradingbot.data.provider import OHLCV_COLUMNS

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "scripts") not in sys.path:
    sys.path.insert(0, str(RAIZ / "scripts"))

import fetch_fixture  # noqa: E402


@pytest.mark.parametrize("symbol", REAL_FIXTURES)
def test_el_fixture_real_cumple_el_contrato(symbol):
    if not real_fixture_path(symbol).is_file():
        pytest.skip(f"falta tests/fixtures/real/{symbol}.csv")
    df = LocalCsvProvider(REAL_FIXTURES_DIR).get_ohlcv(symbol)
    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert len(df) > 2000  # el más corto es XLRE, que arranca en 2016
    assert df.index.is_monotonic_increasing and not df.index.has_duplicates

    # y el CSV coincide con su sidecar: si alguien lo reescribe a mano, se nota
    meta = sidecar_real(symbol)
    assert meta["rows"] == len(df)
    assert meta["adjusted"] is True
    assert df.index[0].strftime("%Y-%m-%d") == meta["first"]
    assert df.index[-1].strftime("%Y-%m-%d") == meta["last"]


@requires_real_fixture("SPY")
def test_backtest_sobre_datos_reales_da_numeros_coherentes():
    config = load_strategy("config/strategies/ema_cross.yaml")
    provider = LocalCsvProvider(REAL_FIXTURES_DIR)
    frames = {"SPY": provider.get_ohlcv("SPY")}

    result = run_backtest(config, frames)
    assert result.metrics["final_equity"] > 0
    assert abs(result.metrics["cagr"]) < 5.0
    assert result.benchmark_metrics["cagr"] == pytest.approx(
        result.benchmark_metrics["cagr"]
    )  # no NaN


# --- la contaminación, que es el motivo del subdirectorio -------------------
def test_la_precedencia_del_proveedor_es_la_que_creemos(tmp_path):
    """Primero el riesgo, escrito como hecho ejecutable: la raíz PISA al subdirectorio.

    Los tres tests de abajo verifican que hoy no pasa. Este verifica *por qué*
    habría que cuidarlo: si algún día ``LocalCsvProvider`` cambiara y el
    subdirectorio pasara a ganar, este test se pone en rojo y los otros tres
    dejan de tener sentido, en vez de quedar como reglas sin motivo.
    """
    (tmp_path / "synthetic").mkdir()
    cabecera = "date,open,high,low,close,volume\n"
    (tmp_path / "synthetic" / "SPY.csv").write_text(
        cabecera + "2020-01-02,1,1,1,1,100\n", encoding="utf-8"
    )
    provider = LocalCsvProvider(tmp_path)
    assert provider.path_for("SPY").parent.name == "synthetic"

    (tmp_path / "SPY.csv").write_text(cabecera + "2020-01-02,2,2,2,2,200\n", encoding="utf-8")
    assert provider.path_for("SPY") == tmp_path / "SPY.csv"  # la raíz ganó


def test_no_hay_ningun_csv_suelto_en_la_raiz_de_fixtures():
    """Nada de ``tests/fixtures/*.csv``: todo CSV vive en un subdirectorio.

    Es la condición que hace imposible la contaminación, y se verifica sobre el
    árbol y no sobre una lista de símbolos: un fixture real nuevo, de un símbolo
    que hoy no existe, también la rompería.
    """
    sueltos = sorted(p.name for p in FIXTURES_DIR.glob("*.csv"))
    assert sueltos == [], (
        f"hay CSV sueltos en tests/fixtures/: {sueltos}. Le pisan el sintético al "
        "universo 'independiente (4)' (ver el docstring de este archivo). Movelos a "
        "tests/fixtures/real/ o tests/fixtures/synthetic/"
    )


def test_el_universo_independiente_resuelve_entero_contra_los_sinteticos():
    """Los 4 símbolos de la plantilla salen de ``synthetic/`` y de ningún otro lado."""
    config = yaml.safe_load(
        (RAIZ / "config/strategies/ema_cross.yaml").read_text(encoding="utf-8")
    )
    provider = LocalCsvProvider(FIXTURES_DIR)
    for symbol in config["universe"]:
        assert provider.path_for(symbol).parent.name == "synthetic", (
            f"{symbol} del universo independiente no sale de tests/fixtures/synthetic/"
        )


def test_el_bajador_no_escribe_en_la_raiz_ni_por_defecto():
    """La contaminación no se evita con disciplina: el default del script la evita.

    ``fetch_fixture.py`` sin ``--out`` tiene que escribir en ``real/``. Mientras
    el default apunte a la raíz, alcanza con un ``python scripts/fetch_fixture.py
    SPY`` distraído para que el universo independiente se vuelva medio real.
    """
    assert fetch_fixture.DESTINO_REAL == REAL_FIXTURES_DIR
    # y el default se lee del parser, no de la constante: son dos cosas que se
    # pueden desincronizar, y la que manda es la del parser
    destino = fetch_fixture.construir_parser().parse_args(["SPY"]).out
    assert destino == REAL_FIXTURES_DIR, (
        f"el --out por defecto de fetch_fixture.py es {destino}, "
        "y tiene que ser tests/fixtures/real/"
    )


def test_los_reales_no_son_alcanzables_desde_la_raiz_de_fixtures():
    """Y al revés: parado en la raíz, un símbolo que solo existe en real/ no aparece.

    Si apareciera, alguien habría agregado ``real`` a los ``subdirs`` del
    proveedor y la separación sería decorativa.
    """
    provider = LocalCsvProvider(FIXTURES_DIR)
    solo_reales = [s for s in REAL_FIXTURES if real_fixture_path(s).is_file()]
    if not solo_reales:
        pytest.skip("todavía no hay fixtures reales")
    for symbol in solo_reales:
        if symbol in ("SPY", "QQQ"):
            continue  # esos dos también son sintéticos; el test de arriba los cubre
        assert not provider.has(symbol), (
            f"{symbol} es alcanzable desde tests/fixtures/ sin pasar por real/"
        )
