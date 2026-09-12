"""Cotejo del motor propio contra `backtesting.py`.

Escribimos el motor para tener control total del modelo de ejecución y de costos
—que es donde estas librerías esconden supuestos—, y el riesgo de eso son bugs
sutiles. La mitigación es esta: la misma estrategia simple en los dos motores,
comparando CAGR, cantidad de trades y max drawdown.

Para que la comparación sea de manzanas con manzanas se apaga todo lo que
`backtesting.py` no hace: sin objetivo, con el stop tan lejos que nunca se toca,
y con el tamaño máximo que permita el cash (que es lo que hace `self.buy()` por
defecto).

**Se corre en dos escenarios: sin costos y con comisión.** La comisión es el
único componente que los dos motores modelan igual (relativa al nocional y
cobrada en las dos puntas), y es el que valida contra una implementación
independiente que no haya doble cobro ni error de signo.

**Por qué el slippage no se compara directo.** El ``spread`` de `backtesting.py`
se aplica UNA sola vez por ida y vuelta: ajusta el precio de entrada y deja el
de salida sin tocar (su propia doc lo dice: *"Before v0.4.0, the commission was
only applied once, like `spread` is now"*). Nosotros lo aplicamos en cada punta,
que es lo que exige la regla de rigor 3 del plan. Son dos modelos distintos, así
que comparar con ``spread`` activado mide la diferencia de modelos y no la
calidad de nuestra implementación. Medido sobre el fixture: con spread el desvío
de CAGR llega al 5.5% en SPY; con comisión sola, los cuatro símbolos quedan
dentro del 5% que pide la definición de terminado.

Lo que queda de diferencia en los dos escenarios no es el modelo de costos, son
dos decisiones nuestras documentadas en README.md: dimensionamos al cierre de la
barra de la señal (ellos, en el fill) y cerramos la última posición al cierre de
la última vela (ellos, en su apertura).
"""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import make_strategy

from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.metrics import cagr, max_drawdown

backtesting = pytest.importorskip("backtesting", reason="backtesting.py no está instalado")

from backtesting import Backtest, Strategy  # noqa: E402
from backtesting.lib import crossover  # noqa: E402

FAST, SLOW = 10, 30


def _sma(values, period):
    return pd.Series(values).rolling(period).mean()


class SmaCross(Strategy):
    def init(self):
        self.fast = self.I(_sma, self.data.Close, FAST)
        self.slow = self.I(_sma, self.data.Close, SLOW)

    def next(self):
        if crossover(self.fast, self.slow):
            self.buy()
        elif crossover(self.slow, self.fast):
            self.position.close()


#: comisión del escenario con costos, en % por lado (0.0005 en fracción)
COMISION_PCT = 0.05


def _our_config(symbol: str, commission_pct: float = 0.0):
    return make_strategy(
        universe=[symbol],
        warmup_bars=SLOW,
        indicators={
            "sma_fast": {"type": "sma", "period": FAST},
            "sma_slow": {"type": "sma", "period": SLOW},
        },
        entry={"all": [{"left": "sma_fast", "op": "crosses_above", "right": "sma_slow"}]},
        exits={
            "signal": {"any": [{"left": "sma_fast", "op": "crosses_below", "right": "sma_slow"}]},
            # stop tan lejos que nunca se toca, y sin objetivo: solo señal
            "hard_stop": {"mode": "pct", "pct": 99.99},
            "take_profit": None,
        },
        risk={
            "position_sizing": {"risk_pct": 100.0},
            "max_position_pct": 100.0,
            "max_open_positions": 1,
        },
        # el slippage queda en cero: ver el docstring del módulo
        execution={"commission_pct": commission_pct, "slippage_pct": 0.0},
    )


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "SPY", "QQQ"])
@pytest.mark.parametrize(
    "commission_pct", [0.0, COMISION_PCT], ids=["sin_costos", "con_comision"]
)
def test_cruce_de_medias_da_lo_mismo_en_los_dos_motores(
    symbol, commission_pct, universe_frames
):
    df = universe_frames[symbol]

    ours = run_backtest(_our_config(symbol, commission_pct), {symbol: df})
    theirs = Backtest(
        df.rename(columns=str.title),
        SmaCross,
        cash=10_000,
        commission=commission_pct / 100.0,
        spread=0.0,
        finalize_trades=True,
    ).run()
    their_equity = theirs["_equity_curve"]["Equity"]

    assert len(ours.trades) == int(theirs["# Trades"])

    nuestro_cagr, su_cagr = ours.metrics["cagr"], cagr(their_equity)
    # 5% relativo, o media décima de punto de CAGR: con CAGR cerca de cero el
    # porcentaje relativo no significa nada
    assert nuestro_cagr == pytest.approx(su_cagr, rel=0.05) or abs(
        nuestro_cagr - su_cagr
    ) < 0.005

    assert ours.metrics["max_drawdown"] == pytest.approx(max_drawdown(their_equity), rel=0.05)
    assert ours.metrics["final_equity"] == pytest.approx(their_equity.iloc[-1], rel=0.05)


@pytest.mark.parametrize("symbol", ["AAPL", "SPY"])
def test_la_comision_pesa_lo_mismo_en_los_dos_motores(symbol, universe_frames):
    """Lo que valida el modelo de costos: cuánta plata se lleva la comisión.

    Comparar equities finales mezcla los costos con las dos diferencias de
    modelo. Comparar *cuánto bajó* la equity al prender la comisión aísla el
    costo, y ahí los dos motores tienen que coincidir de cerca.
    """
    df = universe_frames[symbol]

    sin = run_backtest(_our_config(symbol, 0.0), {symbol: df}).metrics["final_equity"]
    con = run_backtest(_our_config(symbol, COMISION_PCT), {symbol: df})
    nuestro_costo = sin - con.metrics["final_equity"]

    def corrida(commission):
        return Backtest(
            df.rename(columns=str.title),
            SmaCross,
            cash=10_000,
            commission=commission,
            spread=0.0,
            finalize_trades=True,
        ).run()["_equity_curve"]["Equity"].iloc[-1]

    su_costo = corrida(0.0) - corrida(COMISION_PCT / 100.0)

    assert nuestro_costo > 0
    assert nuestro_costo == pytest.approx(su_costo, rel=0.05)

    # y la comisión reportada es exactamente 0.05% del nocional de cada punta
    nocional = sum(
        t.entry_price * t.shares + t.exit_price * t.shares for t in con.trades
    )
    assert con.metrics["total_commission"] == pytest.approx(
        nocional * COMISION_PCT / 100.0
    )
