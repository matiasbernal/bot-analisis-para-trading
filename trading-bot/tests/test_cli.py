"""La CLI, tal como la corre la definición de terminado."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from tradingbot.cli import app

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]


def test_backtest_sobre_los_fixtures_imprime_el_informe_con_benchmark():
    result = runner.invoke(
        app,
        [
            "backtest",
            "--strategy", str(ROOT / "config/strategies/ema_cross.yaml"),
            "--data", str(ROOT / "tests/fixtures"),
        ],
    )
    assert result.exit_code == 0, result.output
    salida = result.output
    assert "BACKTEST · ema_cross_trend_filter" in salida
    assert "Buy & hold" in salida            # benchmark obligatorio
    assert "CAGR" in salida and "Max drawdown" in salida
    assert "Salidas por regla" in salida
    assert "Fiabilidad" in salida
    assert "NaN" not in salida


def test_backtest_escribe_informe_y_manifiesto(tmp_path):
    report = tmp_path / "informe.html"
    manifest = tmp_path / "manifiesto.json"
    result = runner.invoke(
        app,
        [
            "backtest",
            "--strategy", str(ROOT / "config/strategies/ema_cross.yaml"),
            "--data", str(ROOT / "tests/fixtures"),
            "--report", str(report),
            "--manifest", str(manifest),
            "--plotly", "cdn",
        ],
    )
    assert result.exit_code == 0, result.output
    assert report.is_file() and report.stat().st_size > 5_000
    datos = json.loads(manifest.read_text(encoding="utf-8"))
    assert datos["strategy"]["name"] == "ema_cross_trend_filter"
    assert len(datos["fingerprint"]) == 64


def test_backtest_acepta_un_solo_simbolo():
    result = runner.invoke(
        app,
        [
            "backtest",
            "--strategy", str(ROOT / "config/strategies/ema_cross.yaml"),
            "--data", str(ROOT / "tests/fixtures"),
            "--symbol", "SPY",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Símbolos      : SPY" in result.output


def test_config_invalida_sale_con_codigo_2_y_mensaje(tmp_path):
    mala = tmp_path / "mala.yaml"
    mala.write_text(
        yaml.safe_dump(
            {
                "name": "mala",
                "universe": ["SPY"],
                "indicators": {"x": {"type": "no_existe"}},
                "entry": {"all": [{"left": "close", "op": ">", "right": 1}]},
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["backtest", "--strategy", str(mala)])
    assert result.exit_code == 2
    assert "no_existe" in result.output


def test_simbolo_sin_datos_avisa_y_falla():
    result = runner.invoke(
        app,
        [
            "backtest",
            "--strategy", str(ROOT / "config/strategies/ema_cross.yaml"),
            "--data", str(ROOT / "tests/fixtures"),
            "--symbol", "NOEXISTE",
        ],
    )
    assert result.exit_code == 1
    assert "No se pudo cargar ningún símbolo" in result.output


def test_avisa_cuando_los_datos_no_cubren_el_rango_pedido():
    """El YAML pide 2010-2025 y el fixture va de 2018 a 2022: tiene que decirlo."""
    result = runner.invoke(
        app,
        [
            "backtest",
            "--strategy", str(ROOT / "config/strategies/ema_cross.yaml"),
            "--data", str(ROOT / "tests/fixtures"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "RANGO RECORTADO" in result.output
    assert "2010-01-01" in result.output and "2025-12-31" in result.output


def test_sin_recorte_no_hay_aviso(universe_frames):
    from conftest import make_strategy

    from tradingbot.backtest.engine import run_backtest
    from tradingbot.reporting.report import period_note

    frames = {"SPY": universe_frames["SPY"]}
    config = make_strategy(
        universe=["SPY"],
        warmup_bars=50,
        backtest={"start": "2018-01-01", "end": "2022-10-14", "initial_cash": 10_000.0},
    )
    assert period_note(run_backtest(config, frames)) == ""


def test_la_ayuda_funciona():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "backtest" in result.output
