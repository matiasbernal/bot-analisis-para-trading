"""Un resultado que no se puede reproducir no es un resultado.

Dos corridas del mismo backtest tienen que dar las mismas métricas y el mismo
manifiesto, byte a byte. La única excepción es ``created_at``, que por
definición cambia: está fuera del fingerprint y de la comparación.
"""

from __future__ import annotations

import json

import pytest
from conftest import make_strategy

from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.manifest import build_manifest, dumps, save_manifest
from tradingbot.config import load_strategy

CONFIG = dict(
    universe=["AAPL", "MSFT", "SPY", "QQQ"],
    warmup_bars=200,
    indicators={
        "ema_fast": {"type": "ema", "period": 20},
        "ema_slow": {"type": "ema", "period": 50},
    },
    entry={"all": [{"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}]},
    exits={
        "signal": {"any": [{"left": "ema_fast", "op": "crosses_below", "right": "ema_slow"}]},
        "hard_stop": {"mode": "atr", "multiple": 2.0},
        "take_profit": {"mode": "rr", "ratio": 3.0},
    },
    execution={"commission_pct": 0.05, "slippage_pct": 0.05},
)


def test_dos_corridas_dan_las_mismas_metricas(universe_frames):
    config = make_strategy(**CONFIG)
    uno = run_backtest(config, universe_frames)
    dos = run_backtest(config, universe_frames)

    assert uno.metrics == dos.metrics
    assert [t.as_row() for t in uno.trades] == [t.as_row() for t in dos.trades]
    assert uno.equity.equals(dos.equity)


def test_el_manifiesto_es_identico_byte_a_byte(universe_frames, tmp_path):
    config = make_strategy(**CONFIG)
    uno = run_backtest(config, universe_frames)
    dos = run_backtest(config, universe_frames)

    m1 = build_manifest(config, universe_frames, uno.metrics)
    m2 = build_manifest(config, universe_frames, dos.metrics)

    assert m1["fingerprint"] == m2["fingerprint"]
    assert dumps(m1, deterministic=True) == dumps(m2, deterministic=True)

    p1 = save_manifest(m1, tmp_path / "uno.json")
    p2 = save_manifest(m2, tmp_path / "dos.json")
    j1, j2 = json.loads(p1.read_text()), json.loads(p2.read_text())
    assert {k: v for k, v in j1.items() if k != "created_at"} == {
        k: v for k, v in j2.items() if k != "created_at"
    }


def test_el_manifiesto_guarda_el_yaml_y_el_hash_de_los_datos(universe_frames):
    config = make_strategy(**CONFIG)
    result = run_backtest(config, universe_frames)
    manifest = build_manifest(config, universe_frames, result.metrics)

    assert manifest["strategy"]["name"] == config.name
    assert manifest["strategy"]["exits"]["hard_stop"]["multiple"] == 2.0
    assert manifest["data"]["symbols"] == sorted(universe_frames)
    assert len(manifest["data"]["hash"]) == 64
    assert "code_commit" in manifest and "tradingbot_version" in manifest


def test_cambiar_un_dato_cambia_el_fingerprint(universe_frames):
    config = make_strategy(**CONFIG)
    result = run_backtest(config, universe_frames)
    original = build_manifest(config, universe_frames, result.metrics)

    tocado = {s: df.copy() for s, df in universe_frames.items()}
    tocado["SPY"].iloc[0, tocado["SPY"].columns.get_loc("close")] += 0.01
    distinto = build_manifest(config, tocado, result.metrics)

    assert original["fingerprint"] != distinto["fingerprint"]


def test_cambiar_la_estrategia_cambia_el_fingerprint(universe_frames):
    result = run_backtest(make_strategy(**CONFIG), universe_frames)
    uno = build_manifest(make_strategy(**CONFIG), universe_frames, result.metrics)
    otra = make_strategy(**{**CONFIG, "exits": {**CONFIG["exits"], "hard_stop": {"multiple": 3.0}}})
    dos = build_manifest(otra, universe_frames, result.metrics)
    assert uno["fingerprint"] != dos["fingerprint"]


def test_la_plantilla_del_repo_corre_sobre_los_fixtures(universe_frames):
    """El comando de la definición de terminado, sin pasar por la CLI."""
    config = load_strategy("config/strategies/ema_cross.yaml")
    result = run_backtest(config, universe_frames)

    assert result.metrics["n_trades"] > 0
    assert result.metrics["final_equity"] > 0
    for key in ("cagr", "max_drawdown", "sharpe", "expectancy_r"):
        value = result.metrics[key]
        assert value == value, f"{key} es NaN"  # NaN != NaN
        assert abs(value) < 100, f"{key} es absurdo: {value}"


def test_sobre_drift_positivo_buy_and_hold_gana_plata(universe_frames):
    """Test de cordura: el sintético tiene drift positivo, el benchmark tiene que subir."""
    config = load_strategy("config/strategies/ema_cross.yaml")
    result = run_backtest(config, universe_frames)
    assert result.benchmark_metrics["cagr"] > 0
    assert result.benchmark.iloc[-1] > result.benchmark.iloc[0]
    assert result.metrics["cagr"] == pytest.approx(result.metrics["cagr"])  # no NaN
