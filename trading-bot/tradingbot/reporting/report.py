"""Informe de backtest: consola y HTML responsive.

El benchmark buy & hold va **siempre** al lado de la estrategia: una estrategia
que rinde menos que comprar y esperar no sirve, por linda que sea la curva.
Y se imprimen las tres cosas que duelen: el semáforo por cantidad de trades, la
concentración del resultado y la racha máxima de pérdidas.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tradingbot.backtest.engine import BacktestResult
from tradingbot.backtest.validation import in_out_metrics
from tradingbot.reporting import charts as charts_mod

TEMPLATES_DIR = Path(__file__).parent / "templates"

#: filas del bloque de métricas: (clave, etiqueta, formato, comparar con benchmark)
METRIC_ROWS: list[tuple[str, str, str, bool]] = [
    ("final_equity", "Equity final", "money", True),
    ("total_return", "Retorno total", "pct", True),
    ("cagr", "CAGR", "pct", True),
    ("max_drawdown", "Max drawdown", "pct", True),
    ("max_drawdown_days", "Duración MDD", "days", True),
    ("sharpe", "Sharpe", "num", True),
    ("sortino", "Sortino", "num", True),
    ("calmar", "Calmar", "num", True),
    ("profit_factor", "Profit factor", "num", False),
    ("win_rate", "Win rate", "pct", False),
    ("expectancy_r", "Expectancy", "r", False),
    ("win_loss_ratio", "Ganancia/pérdida media", "num", False),
    ("n_trades", "Trades", "int", False),
    ("max_consecutive_losses", "Racha de pérdidas", "int", False),
    ("top5_concentration", "P&L de los 5 mejores", "pct", False),
    ("exposure_pct", "Tiempo en mercado", "pct", False),
]


# --- formato ---------------------------------------------------------------
def _fmt(value: Any, kind: str) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and (math.isnan(value)):
        return "—"
    if isinstance(value, float) and math.isinf(value):
        return "∞"
    if kind == "pct":
        return f"{value * 100:.2f}%"
    if kind == "money":
        return f"${value:,.0f}"
    if kind == "num":
        return f"{value:.2f}"
    if kind == "r":
        return f"{value:+.2f}R"
    if kind == "int":
        return f"{int(value)}"
    if kind == "days":
        return f"{int(value)} d"
    return str(value)


def _klass(key: str, value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    if key in {"max_drawdown", "max_consecutive_losses"}:
        return ""
    if key in {"cagr", "total_return", "expectancy_r"}:
        return "pos" if value > 0 else "neg"
    return ""


# --- bloques del informe ---------------------------------------------------
def exit_breakdown(trades_frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Cuántos trades salió por cada regla y con qué resultado medio."""
    if trades_frame.empty:
        return []
    buckets: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for _, row in trades_frame.iterrows():
        for reason in str(row["exit_reasons"]).split(","):
            buckets[reason].append((row["pnl"], row["pnl_r"]))

    total = len(trades_frame)
    rows = []
    for reason, values in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        avg_pnl = sum(v[0] for v in values) / len(values)
        avg_r = sum(v[1] for v in values) / len(values)
        rows.append(
            {
                "reason": reason,
                "count": len(values),
                "pct": f"{len(values) / total * 100:.0f}%",
                "avg_pnl": f"${avg_pnl:,.0f}",
                "avg_r": f"{avg_r:+.2f}R",
                "klass": "pos" if avg_r > 0 else "neg",
            }
        )
    return rows


def warnings_for(result: BacktestResult) -> list[dict[str, Any]]:
    """Lo que un informe honesto dice aunque duela."""
    out: list[dict[str, Any]] = []
    n = int(result.metrics["n_trades"])
    if n < 30:
        out.append(
            {
                "strong": True,
                "text": f"Con {n} trades NO SE PUEDE CONCLUIR NADA. "
                "Un 60% de aciertos sobre 12 operaciones es ruido.",
            }
        )
    elif n < 100:
        out.append(
            {
                "strong": False,
                "text": f"Con {n} trades las conclusiones son débiles. "
                "Hacen falta 100+ para que la estadística signifique algo.",
            }
        )

    concentration = result.metrics.get("top5_concentration")
    if isinstance(concentration, float) and not math.isnan(concentration) and concentration > 0.8:
        out.append(
            {
                "strong": False,
                "text": f"El {concentration * 100:.0f}% del P&L viene de los 5 mejores trades: "
                "el resultado depende de un puñado de operaciones, no del sistema.",
            }
        )

    strat = result.metrics["cagr"]
    bench = result.benchmark_metrics["cagr"]
    if isinstance(strat, float) and isinstance(bench, float) and strat < bench:
        out.append(
            {
                "strong": False,
                "text": f"La estrategia ({strat * 100:.1f}% CAGR) rinde menos que comprar y "
                f"esperar ({bench * 100:.1f}%). Por ahora no justifica operar.",
            }
        )

    out.append(
        {
            "strong": False,
            "text": "Universo elegido con información posterior: los resultados sobre acciones "
            "que hoy existen son optimistas (sesgo de supervivencia).",
        }
    )
    return out


def _cards(result: BacktestResult) -> list[dict[str, str]]:
    cards = []
    for key, label, kind, compare in METRIC_ROWS:
        value = result.metrics.get(key)
        cards.append(
            {
                "label": label,
                "value": _fmt(value, kind),
                "bench": (
                    _fmt(result.benchmark_metrics.get(key), kind)
                    if compare and key in result.benchmark_metrics
                    else ""
                ),
                "klass": _klass(key, value),
            }
        )
    return cards


# --- consola ---------------------------------------------------------------
def render_console(result: BacktestResult, manifest: dict | None = None) -> str:
    """Informe de texto. Es lo que imprime ``tradingbot backtest``."""
    metrics, bench = result.metrics, result.benchmark_metrics
    lines: list[str] = []
    add = lines.append

    add("=" * 64)
    add(f"BACKTEST · {result.config.name}")
    add("=" * 64)
    add(f"Símbolos      : {', '.join(result.symbols)}")
    add(
        f"Período       : {result.equity.index[0]:%Y-%m-%d} → "
        f"{result.equity.index[-1]:%Y-%m-%d}  ({len(result.equity)} velas)"
    )
    add(
        f"Costos        : comisión {result.config.execution.commission_pct}% + "
        f"slippage {result.config.execution.slippage_pct}% por lado"
    )
    add(
        f"Ejecución     : señal al cierre de t, fill en la apertura de t+1 "
        f"({result.config.execution.fill_on})"
    )
    add("")
    add(f"{'Métrica':<26}{'Estrategia':>16}{'Buy & hold':>16}")
    add("-" * 58)
    for key, label, kind, compare in METRIC_ROWS:
        left = _fmt(metrics.get(key), kind)
        right = _fmt(bench.get(key), kind) if compare and key in bench else ""
        add(f"{label:<26}{left:>16}{right:>16}")
    add("")
    add(f"Fiabilidad    : {metrics['reliability']} ({metrics['n_trades']} trades)")
    add(
        f"Costos totales: comisión ${metrics['total_commission']:,.2f} + "
        f"slippage ${metrics['total_slippage']:,.2f}"
    )

    breakdown = exit_breakdown(result.trades_frame)
    if breakdown:
        add("")
        add("Salidas por regla")
        add("-" * 58)
        add(f"{'Motivo':<20}{'Trades':>8}{'%':>6}{'P&L medio':>14}{'R medio':>10}")
        for row in breakdown:
            add(
                f"{row['reason']:<20}{row['count']:>8}{row['pct']:>6}"
                f"{row['avg_pnl']:>14}{row['avg_r']:>10}"
            )

    split = in_out_metrics(result.equity, result.trades, result.config.backtest.in_sample_end)
    if split:
        add("")
        add(f"In-sample / out-of-sample (corte {split['cut']})")
        add("-" * 58)
        add(f"{'Tramo':<20}{'CAGR':>12}{'MDD':>12}{'Trades':>8}{'Expect.':>10}")
        for label, key in (("in-sample", "in_sample"), ("out-of-sample", "out_of_sample")):
            m = split[key]
            add(
                f"{label:<20}{_fmt(m['cagr'], 'pct'):>12}{_fmt(m['max_drawdown'], 'pct'):>12}"
                f"{m['n_trades']:>8}{_fmt(m['expectancy_r'], 'r'):>10}"
            )

    for warning in warnings_for(result):
        add("")
        add(("!! " if warning["strong"] else " · ") + warning["text"])

    if result.rejections:
        add("")
        add(f"Señales rechazadas: {len(result.rejections)}")
        counts: dict[str, int] = defaultdict(int)
        for rejection in result.rejections:
            counts[rejection.reason] += 1
        for reason, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            add(f"  {count:>4}  {reason}")

    if manifest:
        add("")
        add(f"Manifiesto    : {manifest['fingerprint'][:16]}  (datos {manifest['data']['hash'][:16]})")

    return "\n".join(lines)


# --- HTML ------------------------------------------------------------------
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_html(
    result: BacktestResult,
    frames: dict[str, pd.DataFrame],
    manifest: dict,
    path: str | Path,
    *,
    plotly: str = "inline",
    max_price_charts: int = 4,
) -> Path:
    """Escribe el informe HTML mobile-first.

    ``plotly='inline'`` embebe la librería en el archivo: pesa más pero el
    informe abre sin internet, que es la situación normal (y la única posible en
    el sandbox). ``plotly='cdn'`` genera un archivo liviano que necesita red.
    """
    trades_frame = result.trades_frame
    include_first: str | bool = "inline" if plotly == "inline" else "cdn"

    equity_html = charts_mod.equity_chart(
        result.equity, result.benchmark, include_js=include_first
    )
    drawdown_html = charts_mod.drawdown_chart(result.equity)
    price_charts = [
        {
            "symbol": symbol,
            "html": charts_mod.price_chart(symbol, frames[symbol], trades_frame),
        }
        for symbol in result.symbols[:max_price_charts]
        if symbol in frames
    ]

    split = in_out_metrics(result.equity, result.trades, result.config.backtest.in_sample_end)
    in_out_rows = []
    if split:
        for label, key in (("in-sample", "in_sample"), ("out-of-sample", "out_of_sample")):
            m = split[key]
            in_out_rows.append(
                {
                    "label": label,
                    "cagr": _fmt(m["cagr"], "pct"),
                    "mdd": _fmt(m["max_drawdown"], "pct"),
                    "n": m["n_trades"],
                    "expectancy": _fmt(m["expectancy_r"], "r"),
                }
            )

    trades_rows = []
    for _, row in trades_frame.iterrows():
        trades_rows.append(
            {
                "symbol": row["symbol"],
                "pnl_r": f"{row['pnl_r']:+.2f}",
                "exit_reasons": row["exit_reasons"],
                "pnl": f"${row['pnl']:,.0f}",
                "entry_date": pd.Timestamp(row["entry_date"]).strftime("%Y-%m-%d"),
                "entry_price": f"{row['entry_price']:.2f}",
                "shares": int(row["shares"]),
                "stop_initial": f"{row['stop_initial']:.2f}",
                "exit_date": pd.Timestamp(row["exit_date"]).strftime("%Y-%m-%d"),
                "exit_price": f"{row['exit_price']:.2f}",
                "bars_held": int(row["bars_held"]),
                "mae_r": f"{row['mae_r']:+.2f}",
                "mfe_r": f"{row['mfe_r']:+.2f}",
                "klass": "pos" if row["pnl"] > 0 else "neg",
            }
        )

    html = _environment().get_template("report.html").render(
        strategy=result.config,
        symbols=result.symbols,
        period={
            "start": result.equity.index[0].strftime("%Y-%m-%d"),
            "end": result.equity.index[-1].strftime("%Y-%m-%d"),
            "bars": len(result.equity),
        },
        metrics=result.metrics,
        cards=_cards(result),
        warnings=warnings_for(result),
        charts={"equity": equity_html, "drawdown": drawdown_html, "prices": price_charts},
        exit_breakdown=exit_breakdown(trades_frame),
        in_out=in_out_rows,
        trades=trades_rows,
        rejections=[
            {"date": r.date.strftime("%Y-%m-%d"), "symbol": r.symbol, "reason": r.reason}
            for r in result.rejections[:200]
        ],
        costs_total=(
            f"${result.metrics['total_commission'] + result.metrics['total_slippage']:,.2f}"
        ),
        manifest=manifest,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
