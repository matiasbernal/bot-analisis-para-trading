"""``warmup_bars`` se descarta antes de generar señales.

Durante el warmup los indicadores ya devuelven números, pero son números que no
coinciden con ninguna referencia: un RSI de Wilder recién sembrado, una EMA con
menos barras que su período. Si el motor los dejara disparar entradas, el
backtest empezaría operando sobre ruido.

El control es el que prueba que la máscara hace algo: con ``warmup_bars=0`` la
misma estrategia dispara en la barra 14 (que es donde el RSI(14) deja de ser
NaN), y con ``warmup_bars=50`` no dispara hasta la 50.
"""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import make_strategy

from tradingbot.backtest.engine import prepare_symbol, run_backtest
from tradingbot.config import load_strategy

PERIODO_RSI = 14
WARMUP = 50


def _config(warmup: int):
    """Entrada y salida que disparan en cuanto el RSI existe."""
    return make_strategy(
        universe=["SPY"],
        warmup_bars=warmup,
        indicators={"rsi": {"type": "rsi", "period": PERIODO_RSI}},
        entry={"all": [{"left": "rsi", "op": "<", "right": 90}]},
        exits={
            "signal": {"any": [{"left": "rsi", "op": "<", "right": 95}]},
            "hard_stop": {"mode": "pct", "pct": 5.0},
            "take_profit": {"ratio": 3.0},
        },
    )


def _primeras(flags) -> list[int]:
    return [i for i, v in enumerate(flags) if v][:3]


def test_sin_mascara_la_senal_dispara_apenas_el_indicador_existe(universe_frames):
    """Control: sin warmup, la primera señal es la barra donde el RSI deja de ser NaN."""
    serie = prepare_symbol(_config(0), "SPY", universe_frames["SPY"])
    assert _primeras(serie.entry) == [PERIODO_RSI, PERIODO_RSI + 1, PERIODO_RSI + 2]
    assert _primeras(serie.exit_signal) == [PERIODO_RSI, PERIODO_RSI + 1, PERIODO_RSI + 2]


def test_con_warmup_no_hay_ninguna_senal_antes(universe_frames):
    serie = prepare_symbol(_config(WARMUP), "SPY", universe_frames["SPY"])
    assert not serie.entry[:WARMUP].any()
    assert not serie.exit_signal[:WARMUP].any()
    assert _primeras(serie.entry) == [WARMUP, WARMUP + 1, WARMUP + 2]
    assert _primeras(serie.exit_signal) == [WARMUP, WARMUP + 1, WARMUP + 2]


def test_el_primer_trade_no_puede_entrar_antes_del_warmup(universe_frames):
    """La señal es de la barra `warmup`; el fill, de la siguiente."""
    result = run_backtest(_config(WARMUP), {"SPY": universe_frames["SPY"]})
    assert result.trades
    posicion = universe_frames["SPY"].index.get_loc(
        pd.Timestamp(result.trades[0].entry_date)
    )
    assert posicion == WARMUP + 1


def test_la_plantilla_del_repo_respeta_sus_200_barras(universe_frames):
    config = load_strategy("config/strategies/ema_cross.yaml")
    result = run_backtest(config, universe_frames)
    assert result.trades

    for trade in result.trades:
        posicion = universe_frames[trade.symbol].index.get_loc(
            pd.Timestamp(trade.entry_date)
        )
        assert posicion > config.warmup_bars, (
            f"{trade.symbol} entró en la barra {posicion} con warmup_bars="
            f"{config.warmup_bars}"
        )


def test_un_warmup_mayor_que_la_serie_no_explota(universe_frames):
    serie = prepare_symbol(_config(10_000), "SPY", universe_frames["SPY"])
    assert not serie.entry.any()
    assert not serie.exit_signal.any()


@pytest.mark.parametrize("warmup", [0, 1, 5, 200])
def test_la_mascara_corta_exactamente_donde_dice(warmup, universe_frames):
    serie = prepare_symbol(_config(warmup), "SPY", universe_frames["SPY"])
    assert not serie.entry[:warmup].any()
    if warmup > PERIODO_RSI:
        assert serie.entry[warmup]  # justo después sí puede disparar
