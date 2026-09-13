#!/usr/bin/env python
"""Barrido del chandelier: ¿el daño es de la capa o de sus dos parámetros?

    python scripts/barrido_trailing.py

Corre la plantilla `ema_cross` con `multiple` en {2,3,4,5} y `activate_after_r`
en {0.5,1.0,2.0}, sobre los dos universos de fixtures, y publica CAGR, expectancy
y la atribución de salidas —con la cuenta de `take_profit` aparte, porque la
hipótesis a falsear es que el trailing de 3 ATR está sacando de los ganadores
grandes antes de que lleguen al objetivo.

======================================================================
ESTO ES EXPLORACIÓN SOBRE SINTÉTICOS, NO UNA DECISIÓN. Vale la misma
etiqueta que el fixture estresado de gaps (ESTADO.md, sección 2): **mide
propiedades del generador, no del mercado**. Un chandelier explota
retrocesos y persistencia, y en un random walk esa estructura la define
`_ohlcv_from_shocks`. La tabla dice cómo responde el MOTOR a sus dos
parámetros —que es una pregunta legítima de mecánica— y no dice, ni puede
decir, qué multiplicador conviene operar. Elegir el que mejor CAGR da acá
sería calibrar contra el generador, que es el error que ESTADO.md §2
existe para evitar.
======================================================================
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import yaml

from tradingbot.backtest.engine import run_backtest
from tradingbot.config import StrategyConfig
from tradingbot.consola import forzar_utf8
from tradingbot.data.local import LocalCsvProvider

RAIZ = Path(__file__).resolve().parents[1]
PLANTILLA = RAIZ / "config/strategies/ema_cross.yaml"

MULTIPLOS = (2.0, 3.0, 4.0, 5.0)
ACTIVACIONES = (0.5, 1.0, 2.0)

UNIVERSOS: dict[str, tuple[Path, bool]] = {
    "sintético independiente (4 símbolos)": (RAIZ / "tests/fixtures", False),
    "sintético correlacionado (10 símbolos)": (RAIZ / "tests/fixtures/correlated", True),
}

#: los motivos que se publican, en el orden en que se leen
MOTIVOS = ("take_profit", "trailing_stop", "gap_trailing_stop", "hard_stop", "gap_stop", "signal")


def corrida(datos: Path, todo_el_directorio: bool, trailing: dict | None):
    """``trailing=None`` apaga la capa: es la fila de línea base de cada tabla."""
    crudo = yaml.safe_load(PLANTILLA.read_text(encoding="utf-8"))
    if todo_el_directorio:
        crudo["universe"] = sorted(p.stem for p in datos.glob("*.csv"))
    if trailing is None:
        crudo["exits"].pop("trailing_stop", None)
    else:
        crudo["exits"]["trailing_stop"] = {
            "mode": "chandelier",
            "atr_period": 14,
            **trailing,
        }
    # la calibración declarada deja de describir la corrida apenas se toca un
    # parámetro, y config.py exige que decir otra versión venga con su motivo
    crudo.pop("calibration", None)
    strategy = StrategyConfig(**crudo)
    provider = LocalCsvProvider(datos)
    frames = {
        s: provider.get_ohlcv(
            s, start=strategy.backtest.start, end=strategy.backtest.end, interval="1d"
        )
        for s in strategy.universe
    }
    return run_backtest(strategy, frames, spy_frame=frames.get("SPY"))


def fila(etiqueta: str, resultado) -> str:
    trades = resultado.rule_trades
    cuenta: Counter = Counter()
    for t in trades:
        for motivo in t.exit_reasons:
            cuenta[motivo] += 1
    m = resultado.metrics
    por_motivo = "  ".join(f"{cuenta.get(k, 0):>3}" for k in MOTIVOS)
    return (
        f"  {etiqueta:<22} {m['cagr'] * 100:>7.2f}%  ${m['final_equity']:>8,.0f}  "
        f"{m['expectancy_r']:>+6.2f}R  {m['profit_factor']:>5.2f}  {len(trades):>4}  {por_motivo}"
    )


def main(argv: list[str] | None = None) -> int:
    # Los scripts imprimen σ, → y √, que una consola cp1252 no puede
    # codificar. Ver tradingbot/consola.py.
    forzar_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    print(__doc__.split("======")[1].strip())

    for nombre, (datos, todo) in UNIVERSOS.items():
        if not datos.is_dir():
            print(f"\n{nombre}: falta {datos}")
            continue
        print("")
        print("=" * 104)
        print(nombre)
        print("=" * 104)
        cab = "  ".join(f"{k[:9]:>3}" for k in MOTIVOS)
        print(
            f"  {'configuración':<22} {'CAGR':>8}  {'equity':>9}  "
            f"{'expect':>7}  {'PF':>5}  {'trad':>4}  {cab}"
        )
        print("  " + "-" * 100)
        print(fila("SIN trailing", corrida(datos, todo, None)))
        for multiple in MULTIPLOS:
            print("  " + "-" * 100)
            for activar in ACTIVACIONES:
                etiqueta = f"{multiple:g} ATR · activa {activar:g}R"
                resultado = corrida(
                    datos, todo, {"multiple": multiple, "activate_after_r": activar}
                )
                print(fila(etiqueta, resultado))
    print("")
    print("  Columnas de motivos, en orden:", ", ".join(MOTIVOS))
    print("")
    print("  RECORDATORIO: series sintéticas. La tabla mide cómo responde el motor a")
    print("  sus dos parámetros, no qué multiplicador conviene operar (ESTADO.md §2).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
