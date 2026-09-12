#!/usr/bin/env python
"""Genera los CSV sintéticos de ``tests/fixtures/synthetic/``.

Son determinísticos (seed fijo): correr esto dos veces produce archivos
idénticos. Se commitean para que ``tradingbot backtest --data tests/fixtures/``
funcione sin red y sin generar nada.

Los CSV reales (SPY.csv, AAPL.csv) van en ``tests/fixtures/`` y tienen
precedencia sobre estos: ``LocalCsvProvider`` busca primero ahí.

Genera dos universos:

* ``tests/fixtures/synthetic/``: series independientes entre sí (ρ ≈ 0). Es el
  de la tanda 1 y sus números están fijados en los tests.
* ``tests/fixtures/correlated/``: series correlacionadas por grupos (tech,
  energía, defensivo, más el índice), que es lo que hace falta para probar
  cualquier cosa que dependa de cómo se mueven juntas — heat de cartera, límite
  por grupo, gaps simultáneos.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from fixtures.synthetic import correlated_universe, synthetic_universe  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "synthetic"
OUT_CORR = ROOT / "tests" / "fixtures" / "correlated"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("universo sin correlación (el de la tanda 1):")
    for symbol, df in synthetic_universe().items():
        path = OUT / f"{symbol}.csv"
        df.to_csv(path, index_label="date")
        print(f"  ✓ {symbol}: {len(df)} velas -> {path.relative_to(ROOT)}")

    OUT_CORR.mkdir(parents=True, exist_ok=True)
    print("\nuniverso correlacionado (para el riesgo de cartera de la tanda 2):")
    for symbol, df in correlated_universe().items():
        path = OUT_CORR / f"{symbol}.csv"
        df.to_csv(path, index_label="date")
        print(f"  ✓ {symbol}: {len(df)} velas -> {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
