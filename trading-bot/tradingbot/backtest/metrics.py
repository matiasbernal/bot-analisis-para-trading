"""Métricas del informe, sin ambigüedad (las fórmulas están fijadas en PLAN.md).

Retornos diarios de la curva de equity; Sharpe = media/desvío × √252 con tasa
libre de riesgo 0; Sortino igual pero con el desvío de los negativos;
CAGR = (E_fin/E_ini)^(365.25/días) − 1; MDD sobre el máximo acumulado;
Calmar = CAGR/|MDD|; Profit Factor = suma ganancias / suma pérdidas;
Expectancy = media de ``pnl_r``.

Más las tres cosas que un informe honesto muestra aunque duelan: cantidad de
trades como semáforo, concentración del resultado en los 5 mejores, y racha
máxima de pérdidas consecutivas.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from tradingbot.backtest.portfolio import Trade

PERIODS_PER_YEAR = 252


def daily_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    start_value, end_value = float(equity.iloc[0]), float(equity.iloc[-1])
    if start_value <= 0 or end_value <= 0:
        return float("nan")
    days = (equity.index[-1] - equity.index[0]).days
    if days <= 0:
        return 0.0
    return (end_value / start_value) ** (365.25 / days) - 1.0


def sharpe(equity: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    rets = daily_returns(equity)
    if len(rets) < 2:
        return 0.0
    std = float(rets.std(ddof=1))
    if std == 0 or math.isnan(std):
        return 0.0
    return float(rets.mean()) / std * math.sqrt(periods_per_year)


def sortino(equity: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    rets = daily_returns(equity)
    if len(rets) < 2:
        return 0.0
    downside = rets[rets < 0]
    if len(downside) < 2:
        return 0.0
    std = float(downside.std(ddof=1))
    if std == 0 or math.isnan(std):
        return 0.0
    return float(rets.mean()) / std * math.sqrt(periods_per_year)


def drawdown_series(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    return equity / peak - 1.0


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float(drawdown_series(equity).min())


def max_drawdown_days(equity: pd.Series) -> int:
    """Días corridos del drawdown más largo (desde el pico hasta recuperarlo)."""
    if equity.empty:
        return 0
    peak_value = float(equity.iloc[0])
    peak_date = equity.index[0]
    worst = 0
    for when, value in equity.items():
        # el día que recupera el pico cierra el drawdown, y esa distancia cuenta
        worst = max(worst, (when - peak_date).days)
        if value >= peak_value:
            peak_value, peak_date = float(value), when
    return int(worst)


def profit_factor(trades: Sequence[Trade]) -> float:
    gains = sum(t.pnl for t in trades if t.pnl > 0)
    losses = -sum(t.pnl for t in trades if t.pnl < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def expectancy_r(trades: Sequence[Trade]) -> float:
    """Expectancy del plan: media de ``pnl_r``. "Cuánto deja un trade típico".

    Cada trade pesa igual, que es lo que se quiere para juzgar la regla. Ojo con
    traducirla a plata multiplicando por el 1R declarado: el R realizado varía
    entre trades (ver ``return_on_risk`` y ``expectancy_money``).
    """
    if not trades:
        return 0.0
    return float(np.mean([t.pnl_r for t in trades]))


def expectancy_money(trades: Sequence[Trade]) -> float:
    """Expectancy en pesos: media de ``pnl``. Es el número que no se malinterpreta."""
    if not trades:
        return 0.0
    return float(np.mean([t.pnl for t in trades]))


def return_on_risk(trades: Sequence[Trade]) -> float:
    """Retorno sobre riesgo desplegado: ``Σ pnl / Σ riesgo real``.

    **No es la expectancy** y no la reemplaza. La expectancy pondera cada trade
    igual; esta pondera cada trade por la plata que puso en juego, así que
    responde otra pregunta: cuánto devolvió cada peso arriesgado. Es la unidad
    correcta para el heat de cartera de la Fase 3, que se calcula sobre riesgo
    en pesos y no contando R nominales.

    Con R constante entre trades las dos coinciden; cuanto más dispersa es la R
    realizada, más se separan.
    """
    riesgo = sum(t.risk_amount for t in trades)
    if riesgo <= 0:
        return 0.0
    return float(sum(t.pnl for t in trades) / riesgo)


def risk_deployed(trades: Sequence[Trade]) -> float:
    """Suma del riesgo real de todos los trades, en pesos."""
    return float(sum(t.risk_amount for t in trades))


def win_rate(trades: Sequence[Trade]) -> float:
    if not trades:
        return 0.0
    return sum(1 for t in trades if t.pnl > 0) / len(trades)


def win_loss_ratio(trades: Sequence[Trade]) -> float:
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [-t.pnl for t in trades if t.pnl < 0]
    if not wins or not losses:
        return 0.0
    return float(np.mean(wins) / np.mean(losses))


def max_consecutive_losses(trades: Sequence[Trade]) -> int:
    """Lo que vas a tener que aguantar en vivo. Mejor saberlo antes."""
    worst = run = 0
    for trade in sorted(trades, key=lambda t: (t.exit_date, t.symbol)):
        run = run + 1 if trade.pnl < 0 else 0
        worst = max(worst, run)
    return worst


def worst_losing_streak_money(trades: Sequence[Trade]) -> float:
    """Cuánta plata costó la peor racha de pérdidas seguidas.

    La racha se cuenta en trades, no en R: multiplicar la cantidad por el 1R
    declarado infla el número, porque el R realizado de cada trade es menor
    (ver README, "La unidad de riesgo"). Acá va la plata, que no miente.
    """
    peor = acumulado = 0.0
    for trade in sorted(trades, key=lambda t: (t.exit_date, t.symbol)):
        if trade.pnl < 0:
            acumulado += trade.pnl
            peor = min(peor, acumulado)
        else:
            acumulado = 0.0
    return float(peor)


def top_trades_concentration(trades: Sequence[Trade], top: int = 5) -> float:
    """Qué fracción de la **ganancia bruta** aportan los ``top`` mejores ganadores.

    El denominador es la suma de los trades ganadores, no el P&L neto. Dividir
    por el neto da números imposibles de leer (252% cuando el neto es chico y
    los ganadores no lo son) y se rompe del todo si el neto es negativo. Con la
    ganancia bruta el número vive siempre entre 0 y 1 y responde la pregunta que
    importa: si da 0.80, cuatro quintos de todo lo que ganaste salió de cinco
    operaciones y el resto del sistema no aporta.

    Con 5 ganadores o menos da exactamente 1.0, que es la respuesta correcta.
    """
    wins = sorted((t.pnl for t in trades if t.pnl > 0), reverse=True)
    if not wins:
        return float("nan")
    return float(sum(wins[:top]) / sum(wins))


#: cuántos ganadores hacen falta para que la concentración signifique algo
MIN_WINNERS_FOR_CONCENTRATION = 10

#: cuánto por encima de lo normal dispara el aviso
CONCENTRATION_ALERT = 1.15


def concentration_baseline(n_winners: int, top: int = 5) -> float:
    """Cuánto aportarían los ``top`` mejores en un sistema sano de ``n`` ganadores.

    El porcentaje crudo no se puede comparar contra un umbral fijo porque depende
    casi por completo de cuántos ganadores hay: con 6 ganadores los 5 mejores son
    el 98% por aritmética, y con 50 son el 32%. Un umbral de 80% salta siempre en
    el primer caso y nunca en el segundo, midiendo la cantidad de trades y no la
    concentración.

    La referencia es la exponencial, que es la cola "normal" de una serie de
    ganancias, y tiene forma cerrada: para ``n`` exponenciales iid, el j-ésimo
    mayor vale en promedio ``Σ_{m=j..n} 1/m`` y la suma total vale ``n``, así que

        baseline(n, k) = Σ_{j=1..k} Σ_{m=j..n} (1/m) / n

    Con n=12 y k=5 da 0.758, contra 0.759 de una simulación de 20.000 corridas
    (``test_concentracion.py`` lo verifica).
    """
    if n_winners <= 0:
        return float("nan")
    if n_winners <= top:
        return 1.0
    total = sum(sum(1.0 / m for m in range(j, n_winners + 1)) for j in range(1, top + 1))
    return min(total / n_winners, 1.0)


def concentration_ratio(trades: Sequence[Trade], top: int = 5) -> float:
    """Concentración observada dividida por la normal para esa cantidad de ganadores.

    1.00 es exactamente lo esperable; 1.30 es un resultado que depende de unos
    pocos trades más de lo que debería. Se lee sin tabla de referencia.
    """
    ganadores = sum(1 for t in trades if t.pnl > 0)
    base = concentration_baseline(ganadores, top)
    observado = top_trades_concentration(trades, top)
    if not base or math.isnan(base) or math.isnan(observado):
        return float("nan")
    return float(observado / base)


def reliability(n_trades: int) -> str:
    """Semáforo: con pocos trades no se puede concluir nada."""
    if n_trades < 30:
        return "insuficiente"
    if n_trades < 100:
        return "débil"
    return "razonable"


def compute_metrics(
    equity: pd.Series,
    trades: Iterable[Trade] = (),
    *,
    exposure: pd.Series | None = None,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> dict[str, float | int | str]:
    """Todas las métricas de una curva de equity y su lista de trades.

    ``exposure`` es la cantidad de posiciones abiertas en cada barra. De ahí sale
    ``exposure_pct``, que mide **la fracción de días con al menos una posición
    abierta**, sin ponderar por cuántas ni por cuánto capital ocupan: con cuatro
    símbolos, un día con una posición y un día con cuatro cuentan igual. La
    exposición media ponderada por capital es otra métrica y no está acá.
    """
    trades = list(trades)
    equity = equity.astype("float64")
    mdd = max_drawdown(equity)
    cagr_value = cagr(equity)

    metrics: dict[str, float | int | str] = {
        "initial_equity": float(equity.iloc[0]) if len(equity) else 0.0,
        "final_equity": float(equity.iloc[-1]) if len(equity) else 0.0,
        "total_return": (
            float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) > 1 else 0.0
        ),
        "cagr": cagr_value,
        "max_drawdown": mdd,
        "max_drawdown_days": max_drawdown_days(equity),
        "sharpe": sharpe(equity, periods_per_year),
        "sortino": sortino(equity, periods_per_year),
        "calmar": (cagr_value / abs(mdd)) if mdd < 0 else 0.0,
        "profit_factor": profit_factor(trades),
        "win_rate": win_rate(trades),
        "expectancy_r": expectancy_r(trades),
        "expectancy_money": expectancy_money(trades),
        "return_on_risk": return_on_risk(trades),
        "risk_deployed": risk_deployed(trades),
        "avg_risk_amount": (
            risk_deployed(trades) / len(trades) if trades else 0.0
        ),
        "win_loss_ratio": win_loss_ratio(trades),
        "n_trades": len(trades),
        "reliability": reliability(len(trades)),
        "max_consecutive_losses": max_consecutive_losses(trades),
        "worst_streak_money": worst_losing_streak_money(trades),
        "top5_concentration": top_trades_concentration(trades),
        "concentration_ratio": concentration_ratio(trades),
        "concentration_baseline": concentration_baseline(
            sum(1 for t in trades if t.pnl > 0)
        ),
        "n_winners": sum(1 for t in trades if t.pnl > 0),
        "avg_bars_held": float(np.mean([t.bars_held for t in trades])) if trades else 0.0,
        "total_commission": float(sum(t.commission for t in trades)),
        "total_slippage": float(sum(t.slippage for t in trades)),
        "exposure_pct": (
            float((exposure > 0).mean()) if exposure is not None and len(exposure) else 0.0
        ),
    }
    return metrics
