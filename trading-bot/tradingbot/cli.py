"""CLI. En la tanda 1 hay un solo comando: ``backtest``.

    tradingbot backtest --strategy config/strategies/ema_cross.yaml --data tests/fixtures/

``scan``, ``status``, ``fill``, ``optimize`` y ``report`` llegan en las tandas
siguientes, sobre este mismo motor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.manifest import build_manifest, save_manifest
from tradingbot.config import ConfigError, load_settings, load_strategy
from tradingbot.data.cache import ParquetCache
from tradingbot.data.local import LocalCsvProvider
from tradingbot.data.validate import DataValidationError
from tradingbot.reporting.report import render_console, render_html

app = typer.Typer(add_completion=False, help="Bot de análisis de trading — swing diario.")


@app.callback()
def main_callback() -> None:
    """Analiza, avisa y mide. No ejecuta órdenes."""


def _provider(data_dir: Optional[Path], settings_path: Optional[Path]):
    """Elige la fuente de datos: CSV locales si se pasó --data, si no la del settings."""
    settings = load_settings(settings_path)
    if data_dir is not None:
        return LocalCsvProvider(data_dir), None
    if settings.provider == "local":
        return LocalCsvProvider(settings.data_dir), None
    if settings.provider == "stooq":
        from tradingbot.data.stooq import StooqProvider

        return StooqProvider(), ParquetCache(settings.cache_dir, StooqProvider())
    from tradingbot.data.yahoo import YahooProvider

    provider = YahooProvider()
    return provider, ParquetCache(settings.cache_dir, provider)


SPY = "SPY"


def _source_label(provider, symbol: str) -> str:
    """De dónde salió una serie, para que el informe no mienta sobre sus datos."""
    if isinstance(provider, LocalCsvProvider):
        try:
            path = provider.path_for(symbol)
        except DataValidationError:
            return provider.name
        if path.parent.name == "synthetic":
            return f"serie SINTÉTICA ({path})"
        return f"CSV local ({path})"
    return provider.name


def _providers(provider, frames: dict) -> dict[str, str]:
    return {sym: _source_label(provider, sym) for sym in sorted(frames)}


def _load_spy(frames: dict, load, provider) -> tuple[object | None, str]:
    """La serie de SPY para el benchmark de mercado, con su rótulo o su motivo."""
    if SPY in frames:
        return frames[SPY], f"{_source_label(provider, SPY)} · ya está en el universo"
    try:
        return load(SPY), _source_label(provider, SPY)
    except Exception as exc:  # noqa: BLE001 - el motivo se imprime, no se traga
        return None, f"no se pudo cargar: {exc}"


@app.command()
def backtest(
    strategy: Path = typer.Option(..., "--strategy", "-s", help="YAML de estrategia."),
    data: Optional[Path] = typer.Option(
        None, "--data", "-d", help="Directorio con CSV locales (fixtures)."
    ),
    symbol: Optional[list[str]] = typer.Option(
        None, "--symbol", help="Restringe el universo a estos símbolos."
    ),
    settings: Optional[Path] = typer.Option(None, "--settings", help="config/settings.yaml"),
    report: Optional[Path] = typer.Option(
        None, "--report", "-r", help="Ruta del informe HTML a escribir."
    ),
    manifest_path: Optional[Path] = typer.Option(
        None, "--manifest", help="Ruta del manifiesto JSON a escribir."
    ),
    plotly: str = typer.Option(
        "inline", "--plotly", help="inline (abre sin internet) | cdn (archivo liviano)."
    ),
    offline: bool = typer.Option(False, "--offline", help="No descargar: usar solo el cache."),
) -> None:
    """Corre un backtest y escribe el informe."""
    try:
        config = load_strategy(strategy)
    except ConfigError as exc:
        typer.secho(f"Configuración inválida:\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    universe = [s.upper() for s in symbol] if symbol else config.universe
    provider, cache = _provider(data, settings)

    def load(sym: str):
        if cache is not None:
            return cache.get(
                sym,
                start=config.backtest.start,
                end=config.backtest.end,
                interval=config.interval,
                offline=offline,
            )
        return provider.get_ohlcv(
            sym,
            start=config.backtest.start,
            end=config.backtest.end,
            interval=config.interval,
        )

    frames = {}
    for sym in universe:
        try:
            frames[sym] = load(sym)
        except DataValidationError as exc:
            typer.secho(f"  ! {sym}: {exc}", fg=typer.colors.YELLOW, err=True)

    if not frames:
        typer.secho(
            "No se pudo cargar ningún símbolo del universo.", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1)

    # SPY se descarga siempre, esté o no en el universo: la regla de rigor 5
    # pide comparar contra el mercado, no solo contra el propio universo
    spy_frame, spy_note = _load_spy(frames, load, provider)

    result = run_backtest(config, frames, spy_frame=spy_frame, spy_note=spy_note)
    manifest = build_manifest(config, frames, result.metrics, providers=_providers(provider, frames))
    result.data_hash = manifest["data"]["hash"]
    result.manifest = manifest

    typer.echo(render_console(result, manifest))

    if report is not None:
        path = render_html(result, frames, manifest, report, plotly=plotly)
        typer.echo(f"\nInforme HTML: {path}")
    if manifest_path is not None:
        typer.echo(f"Manifiesto:   {save_manifest(manifest, manifest_path)}")


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
