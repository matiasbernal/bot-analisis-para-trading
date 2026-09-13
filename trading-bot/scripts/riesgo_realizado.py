#!/usr/bin/env python
"""Distribución del riesgo inicial realizado, en unidades del riesgo objetivo.

El sizing calcula las acciones al cierre de la barra de la señal y la orden se
llena en la apertura siguiente, así que el riesgo que termina teniendo cada
trade no es exactamente el 1R que pide el YAML. Este script mide cuánto se
desvía, para decidir con el número y no a ojo.

    python scripts/riesgo_realizado.py \
        --strategy config/strategies/ema_cross_sin_trailing.yaml \
        --data tests/fixtures/

La plantilla por defecto es la que tiene el trailing APAGADO, y eso es a
propósito: esto mide el lado de la entrada. Con una capa de salida prendida, el
tamaño de cada posición pasa a depender de cuándo salieron las anteriores (por
el cash y la equity), y el número deja de medir el sizing.

Riesgo realizado = acciones × riesgo por acción (en pesos).
Riesgo objetivo  = equity al cierre de la señal × risk_pct.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from tradingbot.backtest.engine import run_backtest
from tradingbot.config import load_strategy
from tradingbot.consola import forzar_utf8
from tradingbot.data.local import LocalCsvProvider


def main(argv: list[str] | None = None) -> int:
    # Los scripts imprimen σ, → y √, que una consola cp1252 no puede
    # codificar. Ver tradingbot/consola.py.
    forzar_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args(argv)

    config = load_strategy(args.strategy)
    provider = LocalCsvProvider(args.data)
    frames = {
        s: provider.get_ohlcv(s, start=config.backtest.start, end=config.backtest.end)
        for s in config.universe
        if provider.has(s)
    }
    result = run_backtest(config, frames)

    risk_pct = config.risk.position_sizing.risk_pct / 100.0
    max_pos = config.risk.max_position_pct / 100.0

    filas = []
    for trade in result.trades:
        index = frames[trade.symbol].index
        i = index.get_loc(pd.Timestamp(trade.entry_date))
        equity = float(result.equity.loc[index[i - 1]])
        close = float(frames[trade.symbol]["close"].iloc[i - 1])
        objetivo = equity * risk_pct
        por_riesgo = math.floor(objetivo / trade.risk_per_share)
        por_concentracion = math.floor(equity * max_pos / close)
        filas.append(
            {
                "symbol": trade.symbol,
                "fecha": trade.entry_date,
                "acciones": trade.shares,
                "riesgo": trade.shares * trade.risk_per_share,
                "objetivo": objetivo,
                "r": trade.shares * trade.risk_per_share / objetivo,
                "ata": "riesgo" if por_riesgo <= por_concentracion else "concentración",
            }
        )

    tabla = pd.DataFrame(filas)
    r = tabla["r"]
    print(f"Trades: {len(tabla)}   (riesgo objetivo = 1.00)")
    print(
        f"  min {r.min():.3f}   p05 {r.quantile(0.05):.3f}   media {r.mean():.3f}   "
        f"mediana {r.median():.3f}   p95 {r.quantile(0.95):.3f}   max {r.max():.3f}   "
        f"desvío {r.std(ddof=1):.3f}"
    )
    print(f"  por encima de 1.00R: {(r > 1.0).sum()}    por debajo de 0.85R: {(r < 0.85).sum()}")
    print()
    print("Qué límite ata el tamaño:")
    print(
        tabla.groupby("ata")
        .agg(trades=("acciones", "size"), r_medio=("r", "mean"), r_min=("r", "min"))
        .to_string()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
