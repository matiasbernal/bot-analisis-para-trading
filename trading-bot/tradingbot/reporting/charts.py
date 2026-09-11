"""Gráficos con Plotly, pensados para la pantalla de un teléfono.

Reglas (PLAN.md, "Mobile-first"): ``responsive: true``, altura relativa al ancho
—la fija el JS del template, no un valor en píxeles—, leyenda abajo, barra de
herramientas oculta y zoom táctil habilitado. El gráfico de precio arranca
mostrando las últimas 60 barras, no los quince años.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

#: velas visibles al abrir el gráfico de precio
INITIAL_BARS = 60

PLOTLY_CONFIG = {
    "responsive": True,
    "displayModeBar": False,
    "scrollZoom": True,
}

_LAYOUT = dict(
    autosize=True,
    margin=dict(l=44, r=12, t=32, b=36),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    hovermode="x unified",
    template="plotly_white",
    dragmode="pan",
    xaxis=dict(fixedrange=False),
)


def _fragment(fig: go.Figure, *, include_js: bool, div_id: str) -> str:
    return fig.to_html(
        full_html=False,
        include_plotlyjs=include_js,
        config=PLOTLY_CONFIG,
        div_id=div_id,
        default_height="100%",
    )


def equity_chart(
    equity: pd.Series, benchmark: pd.Series, *, include_js: str | bool = False
) -> str:
    """Curva de equity de la estrategia contra buy & hold."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=equity.index, y=equity.to_numpy(), name="Estrategia", mode="lines")
    )
    fig.add_trace(
        go.Scatter(
            x=benchmark.index,
            y=benchmark.to_numpy(),
            name="Buy & hold",
            mode="lines",
            line=dict(dash="dot"),
        )
    )
    fig.update_layout(**_LAYOUT, yaxis_title="Equity")
    return _fragment(fig, include_js=include_js, div_id="chart-equity")


def drawdown_chart(equity: pd.Series, *, include_js: str | bool = False) -> str:
    """Drawdown de la estrategia, en porcentaje sobre el máximo acumulado."""
    drawdown = (equity / equity.cummax() - 1.0) * 100.0
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=drawdown.index,
            y=drawdown.to_numpy(),
            name="Drawdown",
            fill="tozeroy",
            mode="lines",
        )
    )
    fig.update_layout(**_LAYOUT, yaxis_title="Drawdown %")
    return _fragment(fig, include_js=include_js, div_id="chart-drawdown")


def price_chart(
    symbol: str,
    df: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    include_js: str | bool = False,
) -> str:
    """Velas con las marcas de entrada y salida y el motivo de cada salida."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=symbol,
            showlegend=False,
        )
    )

    if not trades.empty:
        mine = trades[trades["symbol"] == symbol]
        if not mine.empty:
            fig.add_trace(
                go.Scatter(
                    x=mine["entry_date"],
                    y=mine["entry_price"],
                    mode="markers",
                    name="Entrada",
                    marker=dict(symbol="triangle-up", size=11, color="#13795b"),
                    hovertext=[f"entrada {p:.2f}" for p in mine["entry_price"]],
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=mine["exit_date"],
                    y=mine["exit_price"],
                    mode="markers",
                    name="Salida",
                    marker=dict(symbol="triangle-down", size=11, color="#b3261e"),
                    hovertext=[
                        f"{reason} · {r:+.2f}R"
                        for reason, r in zip(mine["exit_reasons"], mine["pnl_r"])
                    ],
                )
            )

    layout = dict(_LAYOUT)
    layout["xaxis"] = dict(fixedrange=False, rangeslider=dict(visible=False))
    if len(df) > INITIAL_BARS:
        layout["xaxis"]["range"] = [df.index[-INITIAL_BARS], df.index[-1]]
    fig.update_layout(**layout, yaxis_title="Precio")
    return _fragment(fig, include_js=include_js, div_id=f"chart-price-{symbol.lower()}")
