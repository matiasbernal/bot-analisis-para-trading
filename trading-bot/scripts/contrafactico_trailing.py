#!/usr/bin/env python
"""El contrafáctico del trailing: ¿cuántas salidas habrían terminado mejor aguantando?

    python scripts/contrafactico_trailing.py

El PLAN pide el contrafáctico para la Fase 3 ("qué habría pasado sin esta capa")
y acá tiene un caso concreto: las 16 salidas por `trailing_stop` de `ema_cross` v3
sobre el fixture independiente. Cada una se empareja —por (símbolo, fecha de
entrada), la misma clave del banco A/B— contra el MISMO trade en la corrida sin
trailing, donde la posición siguió viva hasta el objetivo, el hard stop o la señal.

Lo que sale de acá no es una opinión sobre el chandelier: es la cuenta de en
cuántos trades la capa dejó plata sobre la mesa y en cuántos evitó una pérdida,
con la distribución de la diferencia. Es el número que el veredicto de empate del
banco A/B no muestra, porque un empate promedia las dos direcciones.

======================================================================
SERIES SINTÉTICAS (ESTADO.md, sección 2). El contrafáctico es exacto como
mecánica —son los mismos trades, la misma serie, el único cambio es la
capa— y por eso responde bien la pregunta "¿qué hizo la capa acá?". Lo
que NO puede hacer es generalizar: cuánta plata deja un chandelier sobre
la mesa depende de retrocesos y persistencia, y en un random walk esa
estructura la define el generador.
======================================================================
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from tradingbot.backtest.ab import emparejar
from tradingbot.backtest.engine import run_backtest
from tradingbot.config import StrategyConfig
from tradingbot.data.local import LocalCsvProvider
from tradingbot.strategy.exits import REASON_TRAILING
from tradingbot.consola import forzar_utf8

RAIZ = Path(__file__).resolve().parents[1]
PLANTILLA = RAIZ / "config/strategies/ema_cross.yaml"

UNIVERSOS: dict[str, tuple[Path, bool]] = {
    "sintético independiente (4 símbolos)": (RAIZ / "tests/fixtures", False),
    "sintético correlacionado (10 símbolos)": (RAIZ / "tests/fixtures/correlated", True),
}


def corrida(datos: Path, todo_el_directorio: bool, *, con_trailing: bool):
    crudo = yaml.safe_load(PLANTILLA.read_text(encoding="utf-8"))
    if todo_el_directorio:
        crudo["universe"] = sorted(p.stem for p in datos.glob("*.csv"))
    if not con_trailing:
        crudo["exits"].pop("trailing_stop", None)
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


def analizar(nombre: str, datos: Path, todo: bool) -> None:
    sin = corrida(datos, todo, con_trailing=False)
    con = corrida(datos, todo, con_trailing=True)
    pareo = emparejar(sin.rule_trades, con.rule_trades)

    # solo los pares donde la salida la decidió el trailing en la corrida v3
    por_trailing = [
        (base, var)
        for base, var in pareo.pares
        if any(REASON_TRAILING in motivo for motivo in var.exit_reasons)
    ]

    print("")
    print("=" * 100)
    print(f"{nombre}  ·  {len(por_trailing)} salidas por trailing, emparejadas")
    print("=" * 100)
    print(
        f"  {'símbolo':<7} {'entrada':<11} {'con trailing':>22}  {'sin trailing (aguantar)':>28}  "
        f"{'delta':>8}"
    )
    print("  " + "-" * 96)

    mejor_aguantar: list[float] = []
    mejor_trailing: list[float] = []
    iguales = 0
    for base, var in sorted(por_trailing, key=lambda p: p[1].entry_date):
        delta = var.pnl_r - base.pnl_r  # + = el trailing ganó; - = convenía aguantar
        motivo_base = "+".join(base.exit_reasons)
        motivo_var = "+".join(var.exit_reasons)
        if abs(delta) < 1e-9:
            iguales += 1
        elif delta > 0:
            mejor_trailing.append(delta)
        else:
            mejor_aguantar.append(delta)
        marca = "  " if abs(delta) < 1e-9 else ("OK" if delta > 0 else "<<")
        print(
            f"  {var.symbol:<7} {str(var.entry_date):<11} "
            f"{motivo_var:>12} {var.pnl_r:>+7.2f}R  "
            f"{motivo_base:>18} {base.pnl_r:>+7.2f}R  {delta:>+7.2f}R {marca}"
        )

    n = len(por_trailing)
    if not n:
        return
    suma_aguantar = sum(mejor_aguantar)
    suma_trailing = sum(mejor_trailing)
    print("  " + "-" * 96)
    print(f"  habría terminado MEJOR aguantando  : {len(mejor_aguantar):>3} de {n} "
          f"({len(mejor_aguantar) / n:.0%})   total {suma_aguantar:>+7.2f}R")
    print(f"  el trailing MEJORÓ el resultado    : {len(mejor_trailing):>3} de {n} "
          f"({len(mejor_trailing) / n:.0%})   total {suma_trailing:>+7.2f}R")
    print(f"  sin cambio (misma salida)          : {iguales:>3} de {n}")
    print(f"  NETO sobre las salidas por trailing: {suma_aguantar + suma_trailing:>+7.2f}R "
          f"({(suma_aguantar + suma_trailing) / n:+.3f}R por trade afectado)")
    if mejor_aguantar:
        peor = min(mejor_aguantar)
        print(f"  el peor caso de aguantar-habría-sido-mejor: {peor:+.2f}R")
    if mejor_trailing:
        print(f"  el mejor rescate del trailing            : {max(mejor_trailing):+.2f}R")

    # a dónde habrían ido a parar si no existiera la capa
    destino: dict[str, int] = {}
    for base, _ in por_trailing:
        clave = "+".join(base.exit_reasons)
        destino[clave] = destino.get(clave, 0) + 1
    print("  sin la capa, esas posiciones habrían salido por: "
          + ", ".join(f"{k} {v}" for k, v in sorted(destino.items(), key=lambda x: -x[1])))


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
        analizar(nombre, datos, todo)
    print("")
    print("  'delta' es pnl_r(con trailing) - pnl_r(sin trailing) para el MISMO trade.")
    print("  Negativo = la capa cortó antes y el trade habría terminado mejor aguantando.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
