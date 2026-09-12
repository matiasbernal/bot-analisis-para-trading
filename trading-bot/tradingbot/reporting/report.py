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
from tradingbot.backtest.metrics import (
    CONCENTRATION_ALERT,
    MIN_WINNERS_FOR_CONCENTRATION,
)
from tradingbot.backtest.poder import (
    SIN_ESTIMAR,
    curva_de_poder,
    poder_lineas,
    poder_por_capa,
    sigma_a_priori,
)
from tradingbot.backtest.validation import in_out_metrics
from tradingbot.reporting import charts as charts_mod

TEMPLATES_DIR = Path(__file__).parent / "templates"

#: filas del bloque de métricas: (clave, etiqueta, formato, comparar con benchmark)
METRIC_ROWS: list[tuple[str, str, str, bool]] = [
    ("final_equity", "Equity final", "money", True),
    ("total_return", "Retorno total", "pct", True),
    ("cagr", "CAGR", "pct", True),
    ("max_drawdown", "Max drawdown", "pct", True),
    ("deepest_drawdown_days", "Duración de ese DD", "days", True),
    ("max_drawdown_days", "DD más largo", "days", True),
    ("sharpe", "Sharpe", "num", True),
    ("sortino", "Sortino", "num", True),
    ("calmar", "Calmar", "num", True),
    ("profit_factor", "Profit factor", "num", False),
    ("win_rate", "Win rate", "pct", False),
    ("expectancy_r", "Expectancy", "r", False),
    ("expectancy_money", "Expectancy en plata", "money_signed", False),
    ("return_on_risk", "Retorno s/ riesgo desplegado", "pct", False),
    ("avg_risk_amount", "Riesgo real medio (1R)", "money2", False),
    ("win_loss_ratio", "Ganancia/pérdida media", "num", False),
    ("n_trades", "Trades", "int", False),
    ("max_consecutive_losses", "Racha de pérdidas", "int", False),
    ("worst_streak_money", "Costo de la peor racha", "money_signed", False),
    ("concentration_ratio", "5 mejores vs. lo normal", "times", False),
    ("exposure_pct", "Días con posición", "pct", False),
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
    if kind == "money2":
        return f"${value:,.2f}"
    if kind == "money_signed":
        return f"${value:+,.2f}"
    if kind == "num":
        return f"{value:.2f}"
    if kind == "times":
        return f"{value:.2f}×"
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

    out.extend(_concentration_warning(result))

    racha = int(result.metrics.get("max_consecutive_losses", 0))
    if racha and n < 100:
        out.append(
            {
                "strong": False,
                "text": f"La racha de {racha} pérdidas seguidas "
                f"(${result.metrics['worst_streak_money']:,.2f}) es UNA observación "
                f"sobre {n} trades, no una estadística: no dice cuál es la racha "
                "esperable, solo la que pasó. Con 100+ trades el número empieza a "
                "significar algo.",
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


def _concentration_warning(result: BacktestResult) -> list[dict[str, Any]]:
    """El aviso de concentración, calibrado contra la cantidad de ganadores.

    Con menos de 10 ganadores el número no distingue un sistema concentrado de
    uno con pocos trades, así que el informe lo dice en vez de callarse o de
    inventar un aviso que no significa nada.
    """
    ganadores = int(result.metrics.get("n_winners", 0))
    observado = result.metrics.get("top5_concentration")
    base = result.metrics.get("concentration_baseline")
    ratio = result.metrics.get("concentration_ratio")

    if not ganadores or not isinstance(observado, float) or math.isnan(observado):
        return []

    if ganadores < MIN_WINNERS_FOR_CONCENTRATION:
        return [
            {
                "strong": False,
                "text": f"Con {ganadores} trades ganadores no se puede evaluar la "
                f"concentración del resultado: con tan pocos, los 5 mejores son casi "
                f"todo por aritmética ({observado * 100:.0f}%, y lo normal para "
                f"{ganadores} ganadores ya es {base * 100:.0f}%).",
            }
        ]

    if ratio > CONCENTRATION_ALERT:
        return [
            {
                "strong": False,
                "text": f"Los 5 mejores trades aportan el {observado * 100:.0f}% de la "
                f"ganancia bruta, {ratio:.2f}× lo normal para {ganadores} ganadores "
                f"({base * 100:.0f}%): el resultado depende de un puñado de "
                f"operaciones, no del sistema.",
            }
        ]
    return []


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
                "spy": (
                    _fmt(result.spy_metrics.get(key), kind)
                    if compare and result.spy_metrics and key in result.spy_metrics
                    else ""
                ),
                "klass": _klass(key, value),
            }
        )
    return cards


def risk_unit_lines(result: BacktestResult) -> list[str]:
    """Qué vale 1R de verdad, y cuánto se equivoca leer la expectancy en plata.

    El plan define la expectancy como la media de ``pnl_r`` y así se usa
    mentalmente: "cuánto deja un trade típico". El problema es traducirla a plata
    multiplicando por el 1R declarado, porque el R realizado es más chico. Este
    bloque pone los dos números uno al lado del otro para que la traducción no
    se haga a ojo.
    """
    trades = result.rule_trades
    if not trades:
        return []
    declarado = sum(t.risk_target for t in trades) / len(trades)
    real = sum(t.risk_amount for t in trades) / len(trades)
    expectancy = float(result.metrics["expectancy_r"])
    en_plata = float(result.metrics["expectancy_money"])

    riesgo_pct = result.config.risk.position_sizing.risk_pct
    ancho = 48
    por_riesgo = int(result.metrics.get("sizing_by_risk", 0))
    por_tope = int(result.metrics.get("sizing_by_cap", 0))
    por_cash = int(result.metrics.get("sizing_by_cash", 0))
    dimensionadas = por_riesgo + por_tope + por_cash

    lines = [
        "",
        "Unidad de riesgo",
        "-" * 58,
        f"  {f'1R declarado por el YAML (risk_pct {riesgo_pct}%)':<{ancho}}${declarado:,.2f}",
        f"  {'1R realizado (acciones × riesgo por acción)':<{ancho}}${real:,.2f}"
        + (f"   ({real / declarado:.2f}× del declarado)" if declarado else ""),
        f"  {'Expectancy (media de pnl_r)':<{ancho}}{expectancy:+.2f}R",
        f"  {'Expectancy en plata (media de pnl)':<{ancho}}${en_plata:+,.2f}",
        f"  {'Retorno sobre riesgo desplegado (Σpnl/Σriesgo)':<{ancho}}"
        f"{result.metrics['return_on_risk'] * 100:+.2f}%",
    ]

    if dimensionadas:
        lines.append(
            f"  {'Quién decidió el tamaño':<{ancho}}"
            f"riesgo {por_riesgo}, tope {por_tope}, cash {por_cash} "
            f"(de {dimensionadas} señales)"
        )
        if por_tope + por_cash:
            lines.append(
                f"       risk_pct NO decidió el tamaño en {por_tope + por_cash} de "
                f"{dimensionadas} señales."
            )

    for aviso in result.sizing_warnings:
        lines.append(f"  AVISO: {aviso}")

    ingenua = expectancy * declarado
    if declarado and abs(ingenua - en_plata) > 0.01 * max(abs(en_plata), 1.0):
        error = abs(ingenua / en_plata - 1) * 100 if en_plata else float("inf")
        lines.append(
            f"  OJO: leer la expectancy como '{expectancy:+.2f}R × ${declarado:,.2f}' da "
            f"${ingenua:+,.2f} por trade,"
        )
        lines.append(
            f"       y el promedio real es ${en_plata:+,.2f}. Esa lectura se equivoca "
            f"{error:.0f}%."
        )
    return lines


def poder_contexto(result: BacktestResult) -> dict[str, Any]:
    """El bloque de poder de medición, para el HTML.

    Va en el informe y no en un script aparte porque es la respuesta a "¿esta
    corrida alcanza para decidir algo?", y esa pregunta se hace mirando el
    informe. Sin el bloque, la tabla de métricas invita a comparar dos corridas
    de frente, que es exactamente el error que el banco A/B existe para evitar.
    """
    trades = result.rule_trades
    if not trades:
        return {}
    sigma = sigma_a_priori(trades)
    return {
        "n": len(trades),
        "sigma": f"{sigma:.2f}R",
        "curva": [
            {
                "fraccion": f"{fraccion:.0%}",
                "afectado": f"{valor.por_afectado:.2f}R",
                "global": f"{valor.sobre_expectancy:.2f}R",
            }
            for fraccion, valor in curva_de_poder(trades, sigma=sigma)
        ],
        "capas": [
            {
                "capa": fila.capa,
                "afectados": fila.n_afectados,
                "fraccion": f"{fila.fraccion:.2f}",
                "mde": f"{fila.mde_afectado:.2f}R",
                "disponible": f"{fila.efecto_disponible:.2f}R",
                "cota": fila.cota,
                "veredicto": fila.veredicto,
                "klass": "pos" if fila.medible else "neg",
            }
            for fila in poder_por_capa(trades, spy=result.spy_data, sigma=sigma)
        ],
        "sin_estimar": [
            {"capa": capa, "motivo": motivo} for capa, motivo in SIN_ESTIMAR.items()
        ],
    }


def period_note(result: BacktestResult) -> str:
    """Aviso cuando los datos no cubren el rango que pide el YAML.

    El informe imprime el período que corrió de verdad; sin este aviso no hay
    forma de saber que no es el que se pidió, y un backtest de 4 años se lee
    como si fuera de 15.
    """
    if not result.period_requested or result.equity.empty:
        return ""
    pedido_start, pedido_end = result.period_requested
    real_start, real_end = result.equity.index[0], result.equity.index[-1]

    faltante = []
    if pedido_start and pd.Timestamp(pedido_start) < real_start:
        faltante.append(f"pedía desde {pedido_start}")
    if pedido_end and pd.Timestamp(pedido_end) > real_end:
        faltante.append(f"hasta {pedido_end}")
    if not faltante:
        return ""
    return (
        f"RANGO RECORTADO: el YAML {' y '.join(faltante)}; los datos disponibles "
        f"van de {real_start:%Y-%m-%d} a {real_end:%Y-%m-%d}"
    )


def open_positions_lines(result: BacktestResult) -> list[str]:
    """Las posiciones que seguían abiertas cuando se acabaron los datos.

    No entran en las estadísticas de trades (no las cerró ninguna regla y son el
    único fill al cierre en vez de en la apertura siguiente), pero su plata está
    en la equity final, así que se reportan aparte con nombre y apellido.
    """
    forced = result.forced_closes
    if not forced:
        return []
    lines = [
        "",
        f"Posiciones abiertas al cierre del período: {len(forced)} "
        "(fuera de las estadísticas de trades, valuadas al último cierre)",
        "-" * 58,
    ]
    for trade in forced:
        lines.append(
            f"  {trade.symbol:<6} entrada {trade.entry_date} · {trade.shares} acciones · "
            f"valuada ${trade.exit_price * trade.shares:,.0f} "
            f"({trade.pnl:+,.0f} = {trade.pnl_r:+.2f}R)"
        )
    return lines


def benchmark_header(result: BacktestResult) -> list[str]:
    """Qué es cada columna de benchmark. Sin esto no se sabe qué se compara."""
    lines = [
        f"Buy & hold    : cartera equiponderada de {len(result.symbols)} símbolos "
        f"({', '.join(result.symbols)}), "
        f"${result.metrics['initial_equity'] / max(len(result.symbols), 1):,.0f} en cada uno"
    ]
    if result.spy_metrics is not None:
        nota = f"SPY           : buy & hold de SPY · {result.spy_note}"
        if result.spy_in_universe:
            nota += "\n                SPY está en el universo: cuenta en las dos columnas"
        lines.append(nota)
    else:
        lines.append(f"SPY           : SIN REFERENCIA DE MERCADO · {result.spy_note}")
    return lines


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
    add(f"Calibración   : {result.config.calibration.as_line()}")
    add(
        f"Período       : {result.equity.index[0]:%Y-%m-%d} → "
        f"{result.equity.index[-1]:%Y-%m-%d}  ({len(result.equity)} velas)"
    )
    if period_note(result):
        add(f"                {period_note(result)}")
    add(
        f"Costos        : comisión {result.config.execution.commission_pct}% + "
        f"slippage {result.config.execution.slippage_pct}% por lado"
    )
    add(
        f"Ejecución     : señal al cierre de t, fill en la apertura de t+1 "
        f"({result.config.execution.fill_on})"
    )
    add("")
    for line in benchmark_header(result):
        add(line)
    add("")
    add(f"{'Métrica':<26}{'Estrategia':>16}{'Buy & hold':>16}{'SPY':>16}")
    add("-" * 74)
    spy = result.spy_metrics or {}
    for key, label, kind, compare in METRIC_ROWS:
        left = _fmt(metrics.get(key), kind)
        right = _fmt(bench.get(key), kind) if compare and key in bench else ""
        tercera = _fmt(spy.get(key), kind) if compare and key in spy else ""
        add(f"{label:<26}{left:>16}{right:>16}{tercera:>16}")
    add("")
    add(f"Fiabilidad    : {metrics['reliability']} ({metrics['n_trades']} trades)")
    add(
        f"Costos totales: comisión ${metrics['total_commission']:,.2f} + "
        f"slippage ${metrics['total_slippage']:,.2f}"
    )

    breakdown = exit_breakdown(result.rule_trades_frame)
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

    for line in risk_unit_lines(result):
        add(line)

    add("")
    for line in poder_lineas(result.rule_trades, spy=result.spy_data):
        add(line)

    for line in open_positions_lines(result):
        add(line)

    split = in_out_metrics(
        result.equity, result.rule_trades, result.config.backtest.in_sample_end
    )
    if split:
        add("")
        add(f"In-sample / out-of-sample (corte {split['cut']})")
        add("-" * 58)
        # el semáforo va por tramo: cada mitad tiene menos trades que el total,
        # y sin el aviso al lado la tabla invita a leer la expectancy como si
        # significara algo
        add(f"{'Tramo':<18}{'CAGR':>11}{'MDD':>11}{'Trades':>8}{'Expect.':>10}{'Fiabilidad':>14}")
        for label, key in (("in-sample", "in_sample"), ("out-of-sample", "out_of_sample")):
            m = split[key]
            add(
                f"{label:<18}{_fmt(m['cagr'], 'pct'):>11}{_fmt(m['max_drawdown'], 'pct'):>11}"
                f"{m['n_trades']:>8}{_fmt(m['expectancy_r'], 'r'):>10}{m['reliability']:>14}"
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
        result.equity, result.benchmark, result.spy, include_js=include_first
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

    split = in_out_metrics(
        result.equity, result.rule_trades, result.config.backtest.in_sample_end
    )
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
                    "reliability": m["reliability"],
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
        calibration=result.config.calibration.as_line(),
        period={
            "start": result.equity.index[0].strftime("%Y-%m-%d"),
            "end": result.equity.index[-1].strftime("%Y-%m-%d"),
            "bars": len(result.equity),
        },
        metrics=result.metrics,
        cards=_cards(result),
        benchmark_header=benchmark_header(result),
        period_note=period_note(result),
        warnings=warnings_for(result),
        charts={"equity": equity_html, "drawdown": drawdown_html, "prices": price_charts},
        exit_breakdown=exit_breakdown(result.rule_trades_frame),
        risk_unit=risk_unit_lines(result)[3:],
        poder=poder_contexto(result),
        open_positions=[
            {
                "symbol": t.symbol,
                "entry_date": str(t.entry_date),
                "shares": t.shares,
                "value": f"${t.exit_price * t.shares:,.0f}",
                "pnl": f"{t.pnl:+,.0f}",
                "pnl_r": f"{t.pnl_r:+.2f}R",
            }
            for t in result.forced_closes
        ],
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
