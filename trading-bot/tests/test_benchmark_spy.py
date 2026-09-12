"""Regla de rigor 5: todo informe compara contra buy & hold y contra SPY.

SPY se carga esté o no en el universo. Si no se puede, la columna dice por qué
en vez de desaparecer en silencio: un informe sin referencia de mercado que no
avisa es peor que uno sin referencia.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_strategy
from typer.testing import CliRunner

from tradingbot.backtest.engine import run_backtest
from tradingbot.cli import app
from tradingbot.reporting.report import benchmark_header, render_console

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()

ESTRATEGIA = dict(
    universe=["AAPL", "MSFT"],
    warmup_bars=200,
    indicators={
        "ema_fast": {"type": "ema", "period": 20},
        "ema_slow": {"type": "ema", "period": 50},
    },
    entry={"all": [{"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}]},
    exits={"hard_stop": {"mode": "atr", "multiple": 2.0}, "take_profit": {"ratio": 3.0}},
)


def test_spy_es_una_serie_aparte_del_equiponderado(universe_frames):
    config = make_strategy(**ESTRATEGIA)
    frames = {s: universe_frames[s] for s in config.universe}
    result = run_backtest(
        config, frames, spy_frame=universe_frames["SPY"], spy_note="serie SINTÉTICA"
    )

    assert result.spy is not None
    assert result.spy_metrics is not None
    assert not result.spy_in_universe  # SPY no está en [AAPL, MSFT]
    assert result.spy.index.equals(result.equity.index)  # mismo índice de fechas
    assert result.spy.iloc[0] == pytest.approx(config.backtest.initial_cash)
    # es otra serie que el equiponderado de AAPL+MSFT
    assert result.spy.iloc[-1] != pytest.approx(result.benchmark.iloc[-1])


def test_spy_paga_los_mismos_costos_de_entrada_una_vez(universe_frames):
    """Misma lógica que el equiponderado: compra en la apertura, con costos."""
    config = make_strategy(**ESTRATEGIA, execution={"commission_pct": 1.0, "slippage_pct": 1.0})
    frames = {s: universe_frames[s] for s in config.universe}
    con_costos = run_backtest(config, frames, spy_frame=universe_frames["SPY"])

    sin = make_strategy(**ESTRATEGIA, execution={"commission_pct": 0.0, "slippage_pct": 0.0})
    sin_costos = run_backtest(sin, frames, spy_frame=universe_frames["SPY"])

    assert con_costos.spy.iloc[-1] < sin_costos.spy.iloc[-1]


def test_sin_spy_la_columna_dice_por_que(universe_frames):
    config = make_strategy(**ESTRATEGIA)
    frames = {s: universe_frames[s] for s in config.universe}
    result = run_backtest(config, frames, spy_note="no se pudo cargar: no hay CSV")

    assert result.spy is None and result.spy_metrics is None
    encabezado = "\n".join(benchmark_header(result))
    assert "SIN REFERENCIA DE MERCADO" in encabezado
    assert "no hay CSV" in encabezado
    assert "SIN REFERENCIA DE MERCADO" in render_console(result)


def test_cuando_spy_esta_en_el_universo_el_informe_lo_dice(universe_frames):
    config = make_strategy(**{**ESTRATEGIA, "universe": ["AAPL", "SPY"]})
    frames = {s: universe_frames[s] for s in config.universe}
    result = run_backtest(config, frames, spy_frame=universe_frames["SPY"])

    assert result.spy_in_universe
    assert "cuenta en las dos columnas" in "\n".join(benchmark_header(result))


def test_la_cli_carga_spy_aunque_no_este_en_el_universo():
    result = runner.invoke(
        app,
        [
            "backtest",
            "--strategy", str(ROOT / "config/strategies/ema_cross.yaml"),
            "--data", str(ROOT / "tests/fixtures"),
            "--symbol", "AAPL",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Símbolos      : AAPL" in result.output
    assert "SPY           : buy & hold de SPY" in result.output
    assert "serie SINTÉTICA" in result.output       # rotulado: acá no hay datos reales
    assert "cuenta en las dos columnas" not in result.output


def test_la_cli_avisa_cuando_no_hay_spy(tmp_path):
    """Directorio de datos con un solo símbolo y sin SPY."""
    import shutil

    shutil.copy(ROOT / "tests/fixtures/synthetic/AAPL.csv", tmp_path / "AAPL.csv")
    result = runner.invoke(
        app,
        [
            "backtest",
            "--strategy", str(ROOT / "config/strategies/ema_cross.yaml"),
            "--data", str(tmp_path),
            "--symbol", "AAPL",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "SIN REFERENCIA DE MERCADO" in result.output
    assert "no hay CSV" in result.output


def test_el_informe_html_trae_la_columna_spy(universe_frames, tmp_path):
    from tradingbot.backtest.manifest import build_manifest
    from tradingbot.reporting.report import render_html

    config = make_strategy(**ESTRATEGIA)
    frames = {s: universe_frames[s] for s in config.universe}
    result = run_backtest(config, frames, spy_frame=universe_frames["SPY"], spy_note="sintética")
    manifest = build_manifest(config, frames, result.metrics)
    path = render_html(result, frames, manifest, tmp_path / "r.html", plotly="cdn")

    html = path.read_text(encoding="utf-8")
    assert "SPY:" in html                      # en las tarjetas
    assert "buy &amp; hold de SPY" in html     # en el encabezado
    assert '"name":"SPY"' in html.replace(" ", "")  # en el gráfico de equity
