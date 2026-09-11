#!/usr/bin/env python
"""Baja datos reales a ``tests/fixtures/`` para usarlos como fixture.

Se corre **una vez en tu máquina** (necesita internet; el sandbox de Claude no
llega a Yahoo) y el resultado se commitea:

    python scripts/fetch_fixture.py SPY AAPL

Hasta que existan esos CSV, los tests que los usan se saltean con el motivo.
No bloquean nada.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+", help="Símbolos a bajar (p.ej. SPY AAPL)")
    parser.add_argument("--years", type=int, default=3, help="Años de historia (default 3)")
    parser.add_argument(
        "--out", type=Path, default=FIXTURES, help="Directorio destino (default tests/fixtures)"
    )
    parser.add_argument(
        "--provider", choices=["yahoo", "stooq"], default="yahoo", help="Fuente de datos"
    )
    args = parser.parse_args(argv)

    if args.provider == "yahoo":
        from tradingbot.data.yahoo import YahooProvider

        provider = YahooProvider()
    else:
        from tradingbot.data.stooq import StooqProvider

        provider = StooqProvider()

    end = date.today()
    start = end - timedelta(days=int(args.years * 365.25) + 5)
    args.out.mkdir(parents=True, exist_ok=True)

    failed = 0
    for symbol in args.symbols:
        try:
            df = provider.get_ohlcv(symbol.upper(), start=str(start), end=str(end))
        except Exception as exc:  # noqa: BLE001 - acá queremos el motivo, no el traceback
            print(f"  ! {symbol}: {exc}", file=sys.stderr)
            failed += 1
            continue
        path = args.out / f"{symbol.upper()}.csv"
        df.to_csv(path, index_label="date")
        print(f"  ✓ {symbol.upper()}: {len(df)} velas {df.index[0]:%Y-%m-%d} → "
              f"{df.index[-1]:%Y-%m-%d} -> {path}")

    if failed:
        print(
            f"\n{failed} símbolo(s) fallaron. Si estás en un entorno sin salida a Yahoo, "
            "corré esto en tu máquina.",
            file=sys.stderr,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
