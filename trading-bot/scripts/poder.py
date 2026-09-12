#!/usr/bin/env python
"""Poder de medición del torneo de capas, sobre los universos que existen hoy.

Es el número que decide si la tanda 2C tiene sentido: cuánto tiene que cambiar
una capa de salida para que el resultado se distinga del ruido, con los datos que
hay. Corre la misma plantilla sobre los dos universos de fixtures y compara.

    python scripts/poder.py

El universo sintético independiente tiene 4 símbolos y el correlacionado 10, con
el mismo período (2018-2022, 1250 velas). La diferencia entre las dos tablas es
todo lo que se gana ampliando el universo sin conseguir más historia: el MDE baja
con 1/√n, así que duplicar los trades lo mejora solo un 30%.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.poder import poder_lineas, sigma_a_priori, trades_necesarios
from tradingbot.config import StrategyConfig
from tradingbot.data.local import LocalCsvProvider

RAIZ = Path(__file__).resolve().parents[1]
PLANTILLA = RAIZ / "config/strategies/ema_cross.yaml"

#: nombre -> (directorio de datos, símbolos o None para tomar todos los CSV del directorio)
UNIVERSOS: dict[str, tuple[Path, list[str] | None]] = {
    # el directorio de fixtures tiene subdirectorios, así que acá el universo es
    # el de la plantilla y no "todos los CSV que haya"
    "sintético independiente (4 símbolos)": (RAIZ / "tests/fixtures", None),
    "sintético correlacionado (10 símbolos)": (RAIZ / "tests/fixtures/correlated", []),
}

#: efectos de referencia para la pregunta "¿cuántos trades harían falta?"
OBJETIVOS = (0.30, 0.50)


def corrida(plantilla: Path, datos: Path, simbolos: list[str] | None = None):
    """``simbolos=None`` usa el universo de la plantilla; ``[]`` toma todo el directorio."""
    config = yaml.safe_load(plantilla.read_text(encoding="utf-8"))
    if simbolos == []:
        simbolos = sorted(p.stem for p in datos.glob("*.csv"))
    if simbolos is None:
        simbolos = config["universe"]
    config["universe"] = simbolos
    strategy = StrategyConfig(**config)
    provider = LocalCsvProvider(datos)
    frames = {
        s: provider.get_ohlcv(
            s, start=strategy.backtest.start, end=strategy.backtest.end, interval="1d"
        )
        for s in simbolos
    }
    return run_backtest(strategy, frames, spy_frame=frames.get("SPY")), frames


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", type=Path, default=PLANTILLA)
    args = parser.parse_args(argv)

    for nombre, (datos, simbolos) in UNIVERSOS.items():
        if not datos.is_dir():
            print(f"\n{nombre}: falta {datos}")
            continue
        resultado, _ = corrida(args.strategy, datos, simbolos)
        trades = resultado.rule_trades

        print("=" * 78)
        print(f"{nombre}  ·  {', '.join(resultado.symbols)}")
        print("=" * 78)
        print("\n".join(poder_lineas(trades, spy=resultado.spy_data)))

        sigma = sigma_a_priori(trades)
        print("")
        print("  cuántos trades harían falta (con σ de este universo):")
        for objetivo in OBJETIVOS:
            for fraccion in (1.0, 0.5, 0.25):
                print(
                    f"    para detectar {objetivo:.2f}R por trade afectado con f={fraccion:.2f}: "
                    f"{trades_necesarios(objetivo, sigma=sigma, fraccion=fraccion)} trades "
                    f"(hoy hay {len(trades)})"
                )
        print("")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
