"""El test más importante del proyecto.

Sin lookahead: el indicador en la barra ``t`` usa solo datos hasta ``t``, la
señal se evalúa al cierre de ``t`` y se ejecuta en la apertura de ``t+1``.

Se verifica de cuatro formas independientes:

1. **Indicadores**: el valor en ``t`` calculado sobre la serie recortada en ``t``
   es idéntico al calculado sobre la serie completa.
2. **Motor**: cortar los datos en una fecha T no cambia ni un trade cerrado
   antes de T. Si el motor espiara el futuro, cambiarían.
3. **Ejecución**: toda entrada se llena en una **apertura**, nunca en un cierre,
   y siempre en la barra siguiente a la de la señal.
4. **Cordura**: un motor deliberadamente tramposo (que mira la evaluación de
   ``t+1``) da resultados absurdamente mejores. Si diera lo mismo, habría un bug.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from conftest import make_strategy

from tradingbot.backtest.engine import run_backtest
from tradingbot.indicators.registry import REGISTRY, compute_indicator
from tradingbot.strategy.engine import build_context, signals_for

CROSS_STRATEGY = dict(
    universe=["AAPL", "MSFT", "SPY", "QQQ"],
    warmup_bars=200,
    indicators={
        "ema_fast": {"type": "ema", "period": 20},
        "ema_slow": {"type": "ema", "period": 50},
        "atr": {"type": "atr", "period": 14},
    },
    entry={"all": [{"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}]},
    exits={
        "signal": {"any": [{"left": "ema_fast", "op": "crosses_below", "right": "ema_slow"}]},
        "hard_stop": {"mode": "atr", "multiple": 2.0, "atr_period": 14},
        "take_profit": {"mode": "rr", "ratio": 3.0},
    },
)


# --- 1. indicadores --------------------------------------------------------
@pytest.mark.parametrize("name", sorted(REGISTRY))
@pytest.mark.parametrize("cut", [250, 400, 599])
def test_indicador_no_usa_el_futuro(name, cut, synthetic_df):
    completo = compute_indicator(name, synthetic_df, {})
    recortado = compute_indicator(name, synthetic_df.iloc[: cut + 1], {})

    if isinstance(completo, pd.DataFrame):
        for col in completo.columns:
            assert completo[col].iloc[cut] == pytest.approx(
                recortado[col].iloc[cut], rel=1e-12, nan_ok=True
            )
    else:
        assert completo.iloc[cut] == pytest.approx(recortado.iloc[cut], rel=1e-12, nan_ok=True)


def test_senales_no_usan_el_futuro(synthetic_df):
    config = make_strategy(**{**CROSS_STRATEGY, "universe": ["SYN"]})
    completas = signals_for(
        config.entry, config.exits.signal, build_context(synthetic_df, config.indicators)
    )
    cut = 500
    recortadas = signals_for(
        config.entry,
        config.exits.signal,
        build_context(synthetic_df.iloc[: cut + 1], config.indicators),
    )
    assert completas["entry"].iloc[cut] == recortadas["entry"].iloc[cut]
    assert completas["exit_signal"].iloc[cut] == recortadas["exit_signal"].iloc[cut]


# --- 2. motor --------------------------------------------------------------
def _closed_trades(result):
    return [
        (
            t.symbol,
            t.entry_date,
            round(t.entry_price, 8),
            t.shares,
            t.exit_date,
            round(t.exit_price, 8),
            round(t.pnl, 8),
            ",".join(t.exit_reasons),
        )
        for t in result.trades
        if "fin_del_backtest" not in t.exit_reasons
    ]


def test_cortar_los_datos_no_cambia_el_pasado(universe_frames):
    config = make_strategy(**CROSS_STRATEGY)
    completo = run_backtest(config, universe_frames)

    corte = universe_frames["SPY"].index[900]
    truncado = run_backtest(
        config, {s: df[df.index <= corte] for s, df in universe_frames.items()}
    )

    pasado_completo = [t for t in _closed_trades(completo) if t[4] <= corte.date()]
    pasado_truncado = [t for t in _closed_trades(truncado) if t[4] <= corte.date()]

    assert pasado_truncado, "el test no prueba nada si no hubo trades antes del corte"
    assert pasado_truncado == pasado_completo


def test_equity_hasta_el_corte_es_identica(universe_frames):
    config = make_strategy(**CROSS_STRATEGY)
    completo = run_backtest(config, universe_frames)
    corte = universe_frames["SPY"].index[900]
    truncado = run_backtest(
        config, {s: df[df.index <= corte] for s, df in universe_frames.items()}
    )
    # la última marca del truncado incluye el cierre forzado de lo que quedó abierto
    izquierda = completo.equity[completo.equity.index < corte]
    derecha = truncado.equity[truncado.equity.index < corte]
    assert np.allclose(izquierda.to_numpy(), derecha.to_numpy(), rtol=0, atol=1e-9)


# --- 3. ejecución ----------------------------------------------------------
def test_la_entrada_se_llena_en_la_apertura_siguiente(universe_frames):
    config = make_strategy(**{**CROSS_STRATEGY, "execution": {"slippage_pct": 0.0}})
    result = run_backtest(config, universe_frames)
    assert result.trades

    for trade in result.trades:
        frame = universe_frames[trade.symbol]
        entrada = pd.Timestamp(trade.entry_date)
        assert trade.entry_price == pytest.approx(float(frame.loc[entrada, "open"]))

        # la señal estaba en la barra ANTERIOR, no en la de la entrada
        posicion = frame.index.get_loc(entrada)
        assert posicion > 0


def test_la_salida_por_senal_se_llena_en_la_apertura_siguiente(universe_frames):
    config = make_strategy(**{**CROSS_STRATEGY, "execution": {"slippage_pct": 0.0}})
    result = run_backtest(config, universe_frames)
    por_senal = [t for t in result.trades if t.exit_reasons == ["signal"]]
    assert por_senal, "no hubo salidas por señal: el test no prueba nada"
    for trade in por_senal:
        frame = universe_frames[trade.symbol]
        assert trade.exit_price == pytest.approx(
            float(frame.loc[pd.Timestamp(trade.exit_date), "open"])
        )


# --- 4. cordura: el motor tramposo --------------------------------------
def test_mirar_el_futuro_da_resultados_absurdos(universe_frames):
    config = make_strategy(**CROSS_STRATEGY)
    honesto = run_backtest(config, universe_frames)
    tramposo = run_backtest(config, universe_frames, lookahead=True)

    assert honesto.metrics["cagr"] < 0.5, "un motor honesto no rinde 50% anual sobre ruido"
    assert tramposo.metrics["cagr"] > 1.0, "el oráculo tiene que ser absurdo, y no lo es"
    assert tramposo.metrics["cagr"] > honesto.metrics["cagr"] * 10
    assert tramposo.metrics["win_rate"] > 0.8
    assert tramposo.metrics["final_equity"] > honesto.metrics["final_equity"] * 5
