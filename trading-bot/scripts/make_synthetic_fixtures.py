#!/usr/bin/env python
"""Genera los CSV sintéticos de ``tests/fixtures/synthetic/``.

Son determinísticos (seed fijo): correr esto dos veces produce archivos
idénticos. Se commitean para que ``tradingbot backtest --data tests/fixtures/``
funcione sin red y sin generar nada.

Los CSV reales (SPY.csv, AAPL.csv) van en ``tests/fixtures/`` y tienen
precedencia sobre estos: ``LocalCsvProvider`` busca primero ahí.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from fixtures.synthetic import synthetic_universe  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "synthetic"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for symbol, df in synthetic_universe().items():
        path = OUT / f"{symbol}.csv"
        df.to_csv(path, index_label="date")
        print(f"  ✓ {symbol}: {len(df)} velas -> {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
