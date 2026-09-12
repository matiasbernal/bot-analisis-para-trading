"""El cierre forzado por fin de datos no es una operación del sistema.

Decisión: queda **fuera** de las estadísticas de trades (win rate, expectancy,
profit factor, atribución de salidas) y se reporta aparte como "posición abierta
al cierre del período". Dos razones:

* no la decidió ninguna regla, así que contarla como trade ensucia justamente la
  estadística que se usa para juzgar las reglas;
* es el único fill del motor que ejecuta al **cierre** y no en la apertura
  siguiente, o sea que ni siquiera comparte el modelo de ejecución del resto.

Lo que sí sigue contando, porque esa plata se movió de verdad: la equity final,
los costos totales y el P&L acumulado.
"""

from __future__ import annotations

import pytest
from conftest import make_strategy
from fixtures.candles import flat, frame

from tradingbot.backtest.engine import run_backtest
from tradingbot.data.validate import validate_ohlcv
from tradingbot.reporting.report import (
    exit_breakdown,
    open_positions_lines,
    render_console,
)

WARMUP = 5


def _una_posicion_abierta():
    """Entra y nunca toca stop ni objetivo: llega abierta al final de los datos."""
    bars = flat(WARMUP + 1) + [
        (100.0, 101.0, 99.0, 100.5),
        (100.5, 101.5, 100.0, 101.0),
    ]
    df = validate_ohlcv(frame(bars), "TEST")
    config = make_strategy(warmup_bars=WARMUP - 1, universe=["TEST"])
    return run_backtest(config, {"TEST": df})


def test_el_cierre_forzado_se_marca(universe_frames):
    result = _una_posicion_abierta()
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reasons == ["fin_del_backtest"]
    assert trade.is_forced_close
    assert result.forced_closes == [trade]
    assert result.rule_trades == []


def test_no_entra_en_las_estadisticas_de_trades():
    result = _una_posicion_abierta()
    assert result.metrics["n_trades"] == 0          # no es un trade del sistema
    assert result.metrics["win_rate"] == 0.0
    assert result.metrics["expectancy_r"] == 0.0
    assert result.metrics["open_at_end"] == 1
    assert result.metrics["open_at_end_pnl"] == pytest.approx(result.trades[0].pnl)


def test_la_plata_sigue_contando():
    """La equity final incluye la liquidación, aunque no sea un trade."""
    result = _una_posicion_abierta()
    esperado = result.config.backtest.initial_cash + sum(t.pnl for t in result.trades)
    assert result.metrics["final_equity"] == pytest.approx(esperado)


def test_los_costos_incluyen_el_cierre_forzado():
    bars = flat(WARMUP + 1) + [(100.0, 101.0, 99.0, 100.5), (100.5, 101.5, 100.0, 101.0)]
    df = validate_ohlcv(frame(bars), "TEST")
    config = make_strategy(
        warmup_bars=WARMUP - 1,
        universe=["TEST"],
        execution={"commission_pct": 0.1, "slippage_pct": 0.1},
    )
    result = run_backtest(config, {"TEST": df})
    assert result.metrics["n_trades"] == 0
    assert result.metrics["total_commission"] == pytest.approx(result.trades[0].commission)
    assert result.metrics["total_commission"] > 0


def test_fuera_de_la_atribucion_de_reglas(universe_frames):
    from tradingbot.config import load_strategy

    result = run_backtest(load_strategy("config/strategies/ema_cross.yaml"), universe_frames)
    motivos = {row["reason"] for row in exit_breakdown(result.rule_trades_frame)}

    assert result.forced_closes, "el fixture no dejó ninguna posición abierta"
    assert "fin_del_backtest" not in motivos
    # la atribución suma exactamente los trades cerrados por una regla
    total = sum(row["count"] for row in exit_breakdown(result.rule_trades_frame))
    assert total == len(result.rule_trades) == result.metrics["n_trades"]
    # y la tabla de trades del informe los sigue mostrando todos
    assert len(result.trades_frame) == len(result.trades)


def test_el_informe_lo_reporta_aparte(universe_frames):
    from tradingbot.config import load_strategy

    result = run_backtest(load_strategy("config/strategies/ema_cross.yaml"), universe_frames)
    lineas = "\n".join(open_positions_lines(result))
    assert "Posiciones abiertas al cierre del período: 1" in lineas
    assert "fuera de las estadísticas de trades" in lineas
    assert result.forced_closes[0].symbol in lineas
    assert "Posiciones abiertas al cierre" in render_console(result)


def test_sin_posiciones_abiertas_no_se_imprime_nada():
    bars = flat(WARMUP + 1) + [
        (100.0, 120.0, 99.0, 118.0),   # sale por objetivo
        (118.0, 119.0, 117.0, 118.0),
        (118.0, 119.0, 117.0, 118.0),
    ]
    df = validate_ohlcv(frame(bars), "TEST")
    config = make_strategy(
        warmup_bars=WARMUP - 1, universe=["TEST"], risk={"max_open_positions": 1}
    )
    result = run_backtest(config, {"TEST": df})
    primeros = [t for t in result.trades if not t.is_forced_close]
    assert primeros and primeros[0].exit_reasons == ["take_profit"]
