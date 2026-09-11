"""Tests sobre los CSV reales (SPY.csv, AAPL.csv).

Esos archivos los genera el usuario en su máquina con
``python scripts/fetch_fixture.py SPY AAPL`` y se commitean. Hasta que existan,
estos tests se saltean con el motivo; no bloquean nada.
"""

from __future__ import annotations

import pytest
from conftest import real_fixture_path, requires_real_fixture

from tradingbot.backtest.engine import run_backtest
from tradingbot.config import load_strategy
from tradingbot.data.local import LocalCsvProvider
from tradingbot.data.provider import OHLCV_COLUMNS


@requires_real_fixture("SPY")
def test_el_fixture_real_cumple_el_contrato():
    df = LocalCsvProvider(real_fixture_path("SPY").parent).get_ohlcv("SPY")
    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert len(df) > 500  # ~3 años de velas diarias
    assert df.index.is_monotonic_increasing and not df.index.has_duplicates


@requires_real_fixture("SPY")
def test_backtest_sobre_datos_reales_da_numeros_coherentes():
    config = load_strategy("config/strategies/ema_cross.yaml")
    provider = LocalCsvProvider(real_fixture_path("SPY").parent)
    frames = {"SPY": provider.get_ohlcv("SPY")}

    result = run_backtest(config, frames)
    assert result.metrics["final_equity"] > 0
    assert abs(result.metrics["cagr"]) < 5.0
    assert result.benchmark_metrics["cagr"] == pytest.approx(
        result.benchmark_metrics["cagr"]
    )  # no NaN
