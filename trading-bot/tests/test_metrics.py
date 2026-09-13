"""Las 12 métricas del informe contra valores calculados a mano.

Nada de esto se compara contra la salida del propio módulo: los valores
esperados salen de aplicar a mano las fórmulas que fija PLAN.md sobre una serie
chica y escrita a dedo, con la aritmética completa en cada docstring.

**La serie**: 17 puntos de equity, 16 retornos diarios en por ciento

    [+2, +2, -3, -3, -2, +3, +3, +3, -2, +3, +2, +2, -1, +2, +2, +2]

sobre 10.000, en días hábiles desde el 2020-01-01 (último: 2020-01-23).
Tiene un drawdown claro (de 10.404 a 9.593) y su recuperación.

**Los trades**: 8 operaciones a mano, 6 ganadoras (300, 200, 150, 100, 50, 25) y
2 perdedoras (-100, -50), con ``pnl_r = pnl / 100``.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tradingbot.backtest.metrics import (
    cagr,
    compute_metrics,
    deepest_drawdown_days,
    drawdown_episodes,
    drawdown_series,
    expectancy_money,
    expectancy_r,
    max_consecutive_losses,
    return_on_risk,
    risk_deployed,
    max_drawdown,
    max_drawdown_days,
    profit_factor,
    reliability,
    sharpe,
    sortino,
    top_trades_concentration,
    win_loss_ratio,
    win_rate,
    worst_losing_streak_money,
)
from tradingbot.backtest.portfolio import Trade

#: retornos diarios en por ciento
RETORNOS = [2, 2, -3, -3, -2, 3, 3, 3, -2, 3, 2, 2, -1, 2, 2, 2]
EQUITY_INICIAL = 10_000.0
INICIO = "2020-01-01"


@pytest.fixture
def equity() -> pd.Series:
    valores = [EQUITY_INICIAL]
    for r in RETORNOS:
        valores.append(valores[-1] * (1 + r / 100))
    return pd.Series(
        valores,
        index=pd.bdate_range(INICIO, periods=len(valores), name="date"),
        name="equity",
        dtype="float64",
    )


def trade(pnl: float, *, dia: int, r: float | None = None) -> Trade:
    """Un trade a mano. ``pnl_r`` es ``pnl/100`` salvo que se diga otra cosa."""
    return Trade(
        symbol="TEST",
        entry_date=pd.Timestamp("2020-01-01").date(),
        entry_price=100.0,
        shares=10,
        risk_per_share=10.0,
        stop_initial=90.0,
        exit_date=(pd.Timestamp("2020-01-01") + pd.Timedelta(days=dia)).date(),
        exit_price=100.0 + pnl / 10,
        exit_reasons=["take_profit" if pnl > 0 else "hard_stop"],
        pnl=pnl,
        pnl_r=pnl / 100 if r is None else r,
        bars_held=5,
        mae_r=-0.5,
        mfe_r=1.5,
        commission=1.0,
        slippage=1.0,
    )


@pytest.fixture
def trades() -> list[Trade]:
    # el orden es por fecha de salida: W L L W W W W W -> racha de pérdidas = 2
    return [
        trade(300, dia=1),
        trade(-100, dia=2),
        trade(-50, dia=3),
        trade(200, dia=4),
        trade(150, dia=5),
        trade(100, dia=6),
        trade(50, dia=7),
        trade(25, dia=8),
    ]


# --------------------------------------------------------------------------
# 1. CAGR
# --------------------------------------------------------------------------
def test_cagr(equity):
    """CAGR = (E_fin/E_ini)^(365.25/días) − 1.

    E_fin/E_ini = 1.02^7 · 0.97^2 · 0.98^2 · 1.03^4 · 0.99 = 1.1565939485
    (los 16 retornos agrupados: siete +2%, dos −3%, dos −2%, cuatro +3%, un −1%)
    días corridos = 2020-01-23 − 2020-01-01 = 22
    CAGR = 1.1565939485^(365.25/22) − 1 = 10.193007457
    """
    crecimiento = 1.02**7 * 0.97**2 * 0.98**2 * 1.03**4 * 0.99
    assert float(equity.iloc[-1] / equity.iloc[0]) == pytest.approx(crecimiento, rel=1e-12)
    assert (equity.index[-1] - equity.index[0]).days == 22
    assert cagr(equity) == pytest.approx(10.193007457, rel=1e-9)


# --------------------------------------------------------------------------
# 2. Max drawdown  3. su duración
# --------------------------------------------------------------------------
def test_max_drawdown(equity):
    """MDD sobre el máximo acumulado.

    El pico es 10.404 (barra 2). Desde ahí vienen −3%, −3%, −2% hasta el mínimo
    de la barra 5: 0.97 · 0.97 · 0.98 − 1 = −0.077918.
    """
    assert float(equity.iloc[2]) == pytest.approx(10_404.0)
    assert float(equity.iloc[5]) == pytest.approx(9_593.3411, abs=1e-4)
    assert max_drawdown(equity) == pytest.approx(-0.077918, rel=1e-9)
    assert drawdown_series(equity).iloc[5] == pytest.approx(-0.077918, rel=1e-9)
    assert drawdown_series(equity).iloc[2] == pytest.approx(0.0)


def test_duracion_del_max_drawdown(equity):
    """Del pico hasta el día que lo recupera, **incluido**.

    Pico en la barra 2 (2020-01-03, 10.404). La barra 7 vale 10.177,58 (todavía
    abajo) y la 8 vale 10.482,90, que lo supera: 2020-01-13.
    2020-01-13 − 2020-01-03 = 10 días corridos.
    """
    assert float(equity.iloc[7]) < 10_404.0 < float(equity.iloc[8])
    assert equity.index[2].strftime("%Y-%m-%d") == "2020-01-03"
    assert equity.index[8].strftime("%Y-%m-%d") == "2020-01-13"
    assert max_drawdown_days(equity) == 10


def test_duracion_de_un_drawdown_que_no_se_recupera():
    """Si nunca recupera, se cuenta hasta la última barra."""
    serie = pd.Series(
        [100.0, 90.0, 80.0, 85.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-31"]),
    )
    assert max_drawdown_days(serie) == 30


# --------------------------------------------------------------------------
# 4. Sharpe
# --------------------------------------------------------------------------
def test_sharpe(equity):
    """Sharpe = media/desvío × √252, tasa libre de riesgo 0.

    media  = 15/16 = 0.9375 %
    Σ(r−m)² = 7·(1.0625)² + 2·(3.9375)² + 2·(2.9375)² + 4·(2.0625)² + (1.9375)²
            = 7.90234375 + 31.0078125 + 17.2578125 + 17.015625 + 3.75390625
            = 76.9375
    desvío (ddof=1) = √(76.9375/15) = √5.1291666667 = 2.2647663603 %
    Sharpe = 0.9375/2.2647663603 × √252 = 6.5712522871
    """
    media = 0.9375
    desvio = math.sqrt(76.9375 / 15)
    assert desvio == pytest.approx(2.2647663603, rel=1e-9)
    assert sharpe(equity) == pytest.approx(media / desvio * math.sqrt(252), rel=1e-9)
    assert sharpe(equity) == pytest.approx(6.5712522871, rel=1e-9)


# --------------------------------------------------------------------------
# 5. Sortino
# --------------------------------------------------------------------------
def test_sortino(equity):
    """Sortino: igual que Sharpe pero con el desvío de los retornos negativos.

    negativos = [−3, −3, −2, −2, −1], media −2.2
    Σ(r−m)² = 2·(0.8)² + 2·(0.2)² + (1.2)² = 1.28 + 0.08 + 1.44 = 2.80
    desvío (ddof=1) = √(2.80/4) = √0.7 = 0.8366600265 %
    Sortino = 0.9375/0.8366600265 × √252 = 17.7878118384
    """
    desvio_negativos = math.sqrt(2.80 / 4)
    assert desvio_negativos == pytest.approx(0.8366600265, rel=1e-9)
    assert sortino(equity) == pytest.approx(
        0.9375 / desvio_negativos * math.sqrt(252), rel=1e-9
    )
    assert sortino(equity) == pytest.approx(17.7878118384, rel=1e-9)


# --------------------------------------------------------------------------
# 6. Calmar
# --------------------------------------------------------------------------
def test_calmar(equity, trades):
    """Calmar = CAGR / |MDD| = 10.193007457 / 0.077918 = 130.8171084608."""
    metrics = compute_metrics(equity, trades)
    assert metrics["calmar"] == pytest.approx(10.193007457 / 0.077918, rel=1e-9)
    assert metrics["calmar"] == pytest.approx(130.8171084608, rel=1e-9)


# --------------------------------------------------------------------------
# 7. Profit factor  8. Win rate  9. Expectancy  10. ganancia/pérdida media
# --------------------------------------------------------------------------
def test_profit_factor(trades):
    """PF = suma de ganancias / suma de pérdidas.

    ganancias = 300+200+150+100+50+25 = 825
    pérdidas  = 100+50 = 150
    PF = 825/150 = 5.5
    """
    assert profit_factor(trades) == pytest.approx(5.5)


def test_win_rate(trades):
    """6 ganadores de 8 operaciones = 0.75."""
    assert win_rate(trades) == pytest.approx(0.75)


def test_expectancy(trades):
    """Expectancy = media de pnl_r.

    (3.0 + 2.0 + 1.5 + 1.0 + 0.5 + 0.25 − 1.0 − 0.5) / 8 = 6.75/8 = 0.84375
    """
    assert expectancy_r(trades) == pytest.approx(0.84375)


def test_ratio_ganancia_perdida_media(trades):
    """ganancia media / pérdida media = (825/6) / (150/2) = 137.5/75 = 1.8333…"""
    assert win_loss_ratio(trades) == pytest.approx(137.5 / 75)
    assert win_loss_ratio(trades) == pytest.approx(1.8333333333, rel=1e-9)


# --------------------------------------------------------------------------
# 11. Cantidad de trades (y el semáforo que va al lado)
# --------------------------------------------------------------------------
def test_cantidad_de_trades_y_semaforo(equity, trades):
    metrics = compute_metrics(equity, trades)
    assert metrics["n_trades"] == 8
    assert metrics["reliability"] == "insuficiente"
    assert reliability(29) == "insuficiente"
    assert reliability(30) == "débil"
    assert reliability(99) == "débil"
    assert reliability(100) == "razonable"


# --------------------------------------------------------------------------
# 12. Tiempo expuesto al mercado
# --------------------------------------------------------------------------
def test_tiempo_expuesto(equity):
    """Fracción de barras con al menos una posición abierta.

    8 barras con posiciones (una de ellas con 3 a la vez, que cuenta igual que
    una) sobre 17 barras = 0.4705882353.
    """
    exposure = pd.Series([0, 1, 2, 3, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 0], index=equity.index)
    metrics = compute_metrics(equity, [], exposure=exposure)
    assert metrics["exposure_pct"] == pytest.approx(8 / 17)


# --------------------------------------------------------------------------
# Los tres indicadores del "informe honesto"
# --------------------------------------------------------------------------
def test_concentracion_del_resultado(trades):
    """Fracción de la GANANCIA BRUTA que aportan los 5 mejores ganadores.

    ganadores ordenados: 300, 200, 150, 100, 50, 25 (suma 825)
    los cinco mejores suman 800 -> 800/825 = 0.9696969697

    El denominador es la ganancia bruta y no el P&L neto: dividir por el neto da
    números mayores a 1 que no se pueden interpretar, y explota si el neto es
    negativo.
    """
    assert top_trades_concentration(trades, top=5) == pytest.approx(800 / 825)
    assert 0.0 <= top_trades_concentration(trades, top=5) <= 1.0


def test_concentracion_con_neto_negativo_sigue_entre_0_y_1():
    """El caso que rompía la fórmula vieja: el neto es negativo."""
    perdedores = [trade(-500, dia=i) for i in range(1, 6)]
    mixto = perdedores + [trade(100, dia=6), trade(50, dia=7)]
    valor = top_trades_concentration(mixto, top=5)
    assert valor == pytest.approx(1.0)  # solo hay 2 ganadores: aportan todo
    assert sum(t.pnl for t in mixto) < 0


def test_concentracion_sin_ganadores_es_nan():
    assert math.isnan(top_trades_concentration([trade(-100, dia=1)]))


def test_racha_maxima_de_perdidas(trades):
    """El orden por fecha de salida es W L L W W W L W: la racha más larga es 2."""
    assert max_consecutive_losses(trades) == 2


# --------------------------------------------------------------------------
# Bordes: nada de esto puede devolver NaN o infinito por sorpresa
# --------------------------------------------------------------------------
def test_sharpe_sin_volatilidad_no_explota():
    plana = pd.Series(
        [100.0] * 5, index=pd.bdate_range("2020-01-01", periods=5), dtype="float64"
    )
    assert sharpe(plana) == 0.0
    assert sortino(plana) == 0.0
    assert max_drawdown(plana) == 0.0


def test_profit_factor_sin_perdidas_es_infinito():
    assert profit_factor([trade(100, dia=1)]) == float("inf")
    assert profit_factor([]) == 0.0


def test_sin_trades_no_explota(equity):
    metrics = compute_metrics(equity, [])
    assert metrics["n_trades"] == 0
    assert metrics["reliability"] == "insuficiente"
    assert metrics["expectancy_r"] == 0.0
    assert metrics["max_consecutive_losses"] == 0


def test_serie_de_un_solo_punto():
    una = pd.Series([10_000.0], index=pd.DatetimeIndex(["2020-01-01"]))
    metrics = compute_metrics(una, [])
    assert metrics["cagr"] == 0.0
    assert metrics["total_return"] == 0.0
    assert metrics["max_drawdown"] == 0.0


def test_ninguna_metrica_es_infinita_en_una_corrida_normal(equity, trades):
    metrics = compute_metrics(equity, trades, exposure=pd.Series(1, index=equity.index))
    for clave, valor in metrics.items():
        if isinstance(valor, float):
            assert not math.isinf(valor), clave
            assert not np.isnan(valor), clave


# --------------------------------------------------------------------------
# La unidad de riesgo: expectancy vs. retorno sobre riesgo desplegado
# --------------------------------------------------------------------------
def _trade_con_riesgo(pnl: float, *, riesgo: float, dia: int) -> Trade:
    """Un trade con riesgo real ``riesgo`` en pesos (acciones × riesgo por acción)."""
    return Trade(
        symbol="TEST",
        entry_date=pd.Timestamp("2020-01-01").date(),
        entry_price=100.0,
        shares=10,
        risk_per_share=riesgo / 10,
        stop_initial=100.0 - riesgo / 10,
        exit_date=(pd.Timestamp("2020-01-01") + pd.Timedelta(days=dia)).date(),
        exit_price=100.0 + pnl / 10,
        exit_reasons=["take_profit" if pnl > 0 else "hard_stop"],
        pnl=pnl,
        pnl_r=pnl / riesgo,
        bars_held=5,
        mae_r=-0.5,
        mfe_r=1.5,
        commission=0.0,
        slippage=0.0,
        risk_target=100.0,
    )


def test_risk_amount_es_acciones_por_riesgo_por_accion(trades):
    """1R en pesos: 10 acciones × $10 de riesgo por acción = $100."""
    assert trades[0].risk_amount == pytest.approx(100.0)
    assert trades[0].as_row()["risk_amount"] == pytest.approx(100.0)


def test_con_r_constante_expectancy_y_retorno_sobre_riesgo_coinciden(trades):
    """Es la razón por la que el test de expectancy a mano sigue valiendo."""
    assert all(t.risk_amount == pytest.approx(100.0) for t in trades)
    assert return_on_risk(trades) == pytest.approx(expectancy_r(trades))
    assert return_on_risk(trades) == pytest.approx(0.84375)


def test_con_r_heterogeneo_se_separan():
    """Tres trades con riesgo real distinto, calculado a mano.

    A: +150 sobre $100 de riesgo  -> +1.50R
    B: -50  sobre $50  de riesgo  -> -1.00R
    C: +40  sobre $200 de riesgo  -> +0.20R

    Expectancy (media de pnl_r) = (1.50 − 1.00 + 0.20)/3 = 0.70/3 = 0.2333…
      cada trade pesa igual, y el de $50 de riesgo pesa lo mismo que el de $200.

    Retorno sobre riesgo desplegado = Σpnl/Σriesgo = (150 − 50 + 40)/(100+50+200)
                                    = 140/350 = 0.40
      cada trade pesa por la plata que puso en juego.

    Expectancy en plata = (150 − 50 + 40)/3 = 140/3 = 46.6666…
    """
    trades = [
        _trade_con_riesgo(150.0, riesgo=100.0, dia=1),
        _trade_con_riesgo(-50.0, riesgo=50.0, dia=2),
        _trade_con_riesgo(40.0, riesgo=200.0, dia=3),
    ]
    assert [t.risk_amount for t in trades] == [100.0, 50.0, 200.0]

    assert expectancy_r(trades) == pytest.approx(0.70 / 3)
    assert expectancy_r(trades) == pytest.approx(0.2333333333, rel=1e-9)
    assert return_on_risk(trades) == pytest.approx(140 / 350)
    assert return_on_risk(trades) == pytest.approx(0.40)
    assert expectancy_money(trades) == pytest.approx(140 / 3)
    assert risk_deployed(trades) == pytest.approx(350.0)

    # la lectura ingenua: 0.2333R x $100 declarados = $23.33 por trade,
    # cuando el promedio real es $46.67. El informe tiene que mostrar las dos.
    assert expectancy_r(trades) * 100 == pytest.approx(23.3333333, rel=1e-6)
    assert expectancy_money(trades) == pytest.approx(46.6666667, rel=1e-6)


def test_retorno_sobre_riesgo_sin_riesgo_no_explota():
    assert return_on_risk([]) == 0.0


def test_costo_de_la_peor_racha_en_plata():
    """Racha L L W L L L W: la peor son las tres últimas, −10 −20 −30 = −60."""
    trades = [
        _trade_con_riesgo(-10.0, riesgo=100.0, dia=1),
        _trade_con_riesgo(-15.0, riesgo=100.0, dia=2),
        _trade_con_riesgo(100.0, riesgo=100.0, dia=3),
        _trade_con_riesgo(-10.0, riesgo=100.0, dia=4),
        _trade_con_riesgo(-20.0, riesgo=100.0, dia=5),
        _trade_con_riesgo(-30.0, riesgo=100.0, dia=6),
        _trade_con_riesgo(50.0, riesgo=100.0, dia=7),
    ]
    assert max_consecutive_losses(trades) == 3
    assert worst_losing_streak_money(trades) == pytest.approx(-60.0)


# --------------------------------------------------------------------------
# Los dos drawdowns: el más largo y el más profundo pueden ser otro episodio
# --------------------------------------------------------------------------
def test_el_dd_mas_largo_y_el_mas_profundo_pueden_ser_distintos():
    """Serie a mano con dos drawdowns: uno largo y poco profundo, otro corto y hondo.

    Valores: 90 (01-01), 100 (01-02), 95 (02-01), 100 (02-11), 80 (02-12), 100 (02-21)

      episodio A: pico 01-02 (100) → valle 02-01 (95, −5%) → recupera 02-11
                  = 40 días corridos
      episodio B: pico 02-11 (100) → valle 02-12 (80, −20%) → recupera 02-21
                  = 10 días corridos

    El más largo es A (40 días) y el más profundo es B (−20%, 10 días). Leer
    "MDD −20%" al lado de "duración 40 d" mezcla dos episodios distintos.
    """
    fechas = pd.to_datetime(
        ["2020-01-01", "2020-01-02", "2020-02-01", "2020-02-11", "2020-02-12", "2020-02-21"]
    )
    serie = pd.Series([90.0, 100.0, 95.0, 100.0, 80.0, 100.0], index=fechas)

    episodios = drawdown_episodes(serie)
    assert len(episodios) == 2

    largo, profundo = episodios
    assert largo["depth"] == pytest.approx(-0.05)
    assert largo["days"] == 40
    assert largo["peak_date"].strftime("%Y-%m-%d") == "2020-01-02"
    assert largo["recovery_date"].strftime("%Y-%m-%d") == "2020-02-11"
    assert profundo["depth"] == pytest.approx(-0.20)
    assert profundo["days"] == 10

    assert max_drawdown(serie) == pytest.approx(-0.20)
    assert max_drawdown_days(serie) == 40        # el más largo
    assert deepest_drawdown_days(serie) == 10    # el del MDD


def test_los_episodios_traen_pico_valle_y_recuperacion(equity):
    """Sobre la serie del archivo hay tres drawdowns; el primero es el hondo.

    El −7.79% del pico de la barra 2, más dos rasguños después (el −2% de la
    barra 9 y el −1% de la barra 13), que recuperan en dos y tres días.
    """
    episodios = drawdown_episodes(equity)
    assert len(episodios) == 3
    assert [round(e["depth"], 4) for e in episodios] == [-0.0779, -0.02, -0.01]
    episodio = episodios[0]
    assert episodio["peak_date"].strftime("%Y-%m-%d") == "2020-01-03"
    assert episodio["trough_date"].strftime("%Y-%m-%d") == "2020-01-08"
    assert episodio["recovery_date"].strftime("%Y-%m-%d") == "2020-01-13"
    assert episodio["depth"] == pytest.approx(-0.077918, rel=1e-9)
    assert episodio["days"] == 10


def test_un_drawdown_que_no_recupera_se_cuenta_hasta_el_final():
    serie = pd.Series(
        [100.0, 90.0, 80.0, 85.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-31"]),
    )
    episodios = drawdown_episodes(serie)
    assert len(episodios) == 1
    assert episodios[0]["recovery_date"].strftime("%Y-%m-%d") == "2020-01-31"
    assert max_drawdown_days(serie) == 30
    assert deepest_drawdown_days(serie) == 30


def test_la_racha_se_reporta_como_observacion_unica():
    """Con pocos trades, la peor racha es un dato, no una estadística."""
    from types import SimpleNamespace

    from conftest import make_strategy

    from tradingbot.reporting.report import warnings_for

    equity = pd.Series(
        [10_000.0, 10_100.0], index=pd.bdate_range("2020-01-01", periods=2)
    )
    pocos = [trade(-100, dia=i) for i in range(1, 6)] + [
        trade(200, dia=i) for i in range(6, 26)
    ]
    resultado = SimpleNamespace(
        metrics=compute_metrics(equity, pocos),
        benchmark_metrics={"cagr": 0.0},
        rule_trades=pocos,
        # config real y no None: `warnings_for` mira `exits.trailing_stop` para
        # decidir si tiene que avisar que el trailing entra por diseño
        config=make_strategy(),
    )
    textos = " ".join(w["text"] for w in warnings_for(resultado))
    assert "UNA observación" in textos
    assert "25 trades" in textos
    assert "-500.00" in textos  # el costo de la racha, en plata
