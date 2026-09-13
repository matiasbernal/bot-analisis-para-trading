"""Fixtures compartidos y helpers de los tests."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fixtures.synthetic import synthetic_ohlcv, synthetic_universe  # noqa: E402

from tradingbot.config import StrategyConfig  # noqa: E402
from tradingbot.data.validate import validate_ohlcv  # noqa: E402

FIXTURES_DIR = TESTS_DIR / "fixtures"
REAL_FIXTURES = ("SPY", "AAPL")


YAHOO_PING = "https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=5d&interval=1d"
STOOQ_PING = "https://stooq.com/q/d/l/?s=spy.us&i=d"


@lru_cache(maxsize=8)
def sondear(url: str) -> tuple[bool, str]:
    """¿Se llega de verdad a ese host, y si no, por qué no?

    No alcanza con abrir el socket: el proxy del entorno acepta la conexión y
    después rechaza el CONNECT con 403. Hay que pedir algo y mirar la respuesta.

    Y no alcanza con distinguir "hay red" de "no hay red". Son dos fallas
    distintas y se arreglan en lugares distintos: si el proxy rechaza el CONNECT
    es la política de red del entorno, que se configura; si el proveedor
    contesta 4xx (Yahoo 429, Stooq 404 sobre el endpoint de CSV) el host está
    permitido y es el proveedor el que no quiere servirle a esta IP, y ahí no
    hay nada que configurar. El motivo del skip dice cuál de las dos es.
    """
    try:
        import requests

        respuesta = requests.get(url, timeout=6)
    except Exception as exc:  # noqa: BLE001 - cualquier falla significa "no hay red"
        return False, f"no se llega al host ({type(exc).__name__})"
    if respuesta.status_code < 400:
        return True, "ok"
    return False, f"el proveedor contesta HTTP {respuesta.status_code} (el host sí es alcanzable)"


def can_reach(url: str) -> bool:
    return sondear(url)[0]


def has_network() -> bool:
    """¿Hay datos de Yahoo? Si no, los tests de red se saltean con el motivo."""
    return can_reach(YAHOO_PING)


def _skip_if_unreachable(url: str, nombre: str):
    alcanzable, motivo = sondear(url)
    return pytest.mark.skipif(
        not alcanzable,
        reason=f"sin datos de {nombre}: {motivo}",
    )


requires_network = _skip_if_unreachable(YAHOO_PING, "Yahoo")
requires_stooq = _skip_if_unreachable(STOOQ_PING, "Stooq")


def real_fixture_path(symbol: str) -> Path:
    return FIXTURES_DIR / f"{symbol.upper()}.csv"


def requires_real_fixture(symbol: str):
    return pytest.mark.skipif(
        not real_fixture_path(symbol).is_file(),
        reason=(
            f"falta tests/fixtures/{symbol.upper()}.csv; generalo en tu máquina con "
            f"`python scripts/fetch_fixture.py {symbol.upper()}`"
        ),
    )


@pytest.fixture
def synthetic_df():
    """Una serie sintética válida (determinística)."""
    return validate_ohlcv(synthetic_ohlcv(bars=600), "SYN")


@pytest.fixture
def universe_frames():
    """El universo sintético completo, validado."""
    return {
        symbol: validate_ohlcv(df, symbol)
        for symbol, df in synthetic_universe().items()
    }


def make_strategy(**overrides) -> StrategyConfig:
    """Estrategia mínima y explícita para los tests del motor.

    Entrada trivial (``close > 0``) para poder forzar el trade en la barra que
    el test quiera, stop por porcentaje (sin warmup de ATR) y costos en cero
    salvo que el test los pida.
    """
    base = {
        "name": "test",
        "universe": ["TEST"],
        "warmup_bars": 0,
        "indicators": {},
        "entry": {"all": [{"left": "close", "op": ">", "right": 0}]},
        "exits": {
            "hard_stop": {"mode": "pct", "pct": 5.0},
            "take_profit": {"mode": "rr", "ratio": 3.0},
        },
        "execution": {"commission_pct": 0.0, "slippage_pct": 0.0},
        "risk": {
            "position_sizing": {"risk_pct": 1.0},
            "max_position_pct": 100.0,
            "max_open_positions": 5,
        },
        "backtest": {"initial_cash": 10_000.0},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return StrategyConfig(**base)
