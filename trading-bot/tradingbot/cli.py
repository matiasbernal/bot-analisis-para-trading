"""CLI. Dos comandos: ``backtest`` y ``comparar``.

    tradingbot backtest --strategy config/strategies/ema_cross.yaml --data tests/fixtures/
    tradingbot comparar --base base.yaml --variante con_trailing.yaml --data tests/fixtures/

``comparar`` es el banco del torneo de capas (PLAN.md): corre dos estrategias
sobre los mismos datos, empareja los trades y devuelve el delta **con su
incertidumbre**. Sin eso, "la capa mejora la expectancy" no es una medición.

``scan``, ``status``, ``fill``, ``optimize`` y ``report`` llegan en las tandas
siguientes, sobre este mismo motor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import typer

from tradingbot.backtest import ab
from tradingbot.backtest.ab import REPLICAS as AB_REPLICAS
from tradingbot.backtest.ab import SEED as AB_SEED
from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.manifest import build_manifest, save_manifest
from tradingbot.backtest.poder import poder_lineas
from tradingbot.config import ConfigError, load_settings, load_strategy, load_universe
from tradingbot.consola import forzar_utf8
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

#: etiquetas por símbolo para ``risk.max_per_group``. Es un archivo aparte del YAML
#: de estrategia porque las etiquetas son del universo, no de la estrategia: dos
#: estrategias sobre los mismos papeles comparten sectores.
UNIVERSE_YAML = Path("config/universe.yaml")


def _grupos(path: Optional[Path], config) -> dict[str, dict[str, str]]:
    """Las etiquetas del universo, o ``{}`` si no hacen falta.

    Si la estrategia no pide ``max_per_group``, no se lee nada: un backtest sin
    límite por grupo no tiene por qué fallar porque falte un archivo que no usa.
    Si sí lo pide y el archivo no está, el error lo dice con la ruta.
    """
    if not config.risk.max_per_group:
        return {}
    path = path or UNIVERSE_YAML
    if not path.is_file():
        raise ConfigError(
            f"risk.max_per_group necesita las etiquetas de {path}, que no existe. "
            "Pasá --universe con la ruta correcta o sacá max_per_group del YAML."
        )
    return load_universe(path)


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


def _cargar(config, universe: list[str], provider, cache, offline: bool):
    """Carga el universo y devuelve ``(frames, load)``. El load sirve para SPY."""

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
    return frames, load


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
    universe: Optional[Path] = typer.Option(
        None, "--universe", help="YAML con las etiquetas por símbolo (config/universe.yaml)."
    ),
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

    simbolos = [s.upper() for s in symbol] if symbol else config.universe
    try:
        grupos = _grupos(universe, config)
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    provider, cache = _provider(data, settings)
    frames, load = _cargar(config, simbolos, provider, cache, offline)

    # SPY se descarga siempre, esté o no en el universo: la regla de rigor 5
    # pide comparar contra el mercado, no solo contra el propio universo
    spy_frame, spy_note = _load_spy(frames, load, provider)

    result = run_backtest(
        config, frames, spy_frame=spy_frame, spy_note=spy_note, groups=grupos
    )
    manifest = build_manifest(config, frames, result.metrics, providers=_providers(provider, frames))
    result.data_hash = manifest["data"]["hash"]
    result.manifest = manifest

    typer.echo(render_console(result, manifest))

    if report is not None:
        path = render_html(result, frames, manifest, report, plotly=plotly)
        typer.echo(f"\nInforme HTML: {path}")
    if manifest_path is not None:
        typer.echo(f"Manifiesto:   {save_manifest(manifest, manifest_path)}")


@app.command()
def comparar(
    base: Path = typer.Option(..., "--base", "-b", help="YAML de la estrategia base."),
    variante: Path = typer.Option(..., "--variante", "-v", help="YAML de la variante."),
    data: Optional[Path] = typer.Option(
        None, "--data", "-d", help="Directorio con CSV locales (fixtures)."
    ),
    settings: Optional[Path] = typer.Option(None, "--settings", help="config/settings.yaml"),
    universe: Optional[Path] = typer.Option(
        None, "--universe", help="YAML con las etiquetas por símbolo (config/universe.yaml)."
    ),
    seed: int = typer.Option(AB_SEED, "--seed", help="Semilla del bootstrap."),
    replicas: int = typer.Option(AB_REPLICAS, "--replicas", help="Réplicas del bootstrap."),
    offline: bool = typer.Option(False, "--offline", help="No descargar: usar solo el cache."),
) -> None:
    """Compara dos estrategias sobre los mismos datos, con incertidumbre.

    Es el banco del torneo de capas: empareja los trades por (símbolo, fecha de
    entrada) y devuelve el delta de expectancy con su intervalo, más el veredicto
    que aplica las dos reglas de desempate del PLAN.
    """
    try:
        config_base = load_strategy(base)
        config_variante = load_strategy(variante)
    except ConfigError as exc:
        typer.secho(f"Configuración inválida:\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    if sorted(config_base.universe) != sorted(config_variante.universe):
        typer.secho(
            "Las dos estrategias tienen universos distintos: el delta mediría el "
            "universo y no la capa.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    provider, cache = _provider(data, settings)
    frames, _ = _cargar(config_base, config_base.universe, provider, cache, offline)

    try:
        grupos_base = _grupos(universe, config_base)
        grupos_variante = _grupos(universe, config_variante)
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    resultado_base = run_backtest(config_base, frames, groups=grupos_base)
    resultado_variante = run_backtest(config_variante, frames, groups=grupos_variante)

    comparacion = ab.comparar(
        resultado_base,
        resultado_variante,
        etiqueta_base=config_base.name,
        etiqueta_variante=config_variante.name,
        seed=seed,
        replicas=replicas,
    )
    typer.echo("\n".join(comparacion.lineas()))

    if _difieren_en_trailing(config_base, config_variante):
        # El banco no sabe qué capa está comparando: aplica las dos reglas de
        # desempate y, ante un empate, dice "queda APAGADA". Para el trailing esa
        # frase se lee al revés de lo que corresponde, así que va la aclaración
        # justo abajo del veredicto y no en un apéndice.
        typer.echo("")
        typer.secho(
            "  OJO CON ESTE VEREDICTO: la capa que cambia entre las dos corridas es el\n"
            "  trailing, y el trailing NO es candidata del torneo. El PLAN lo declara\n"
            "  línea base de las plantillas (hard stop + trailing), así que un empate\n"
            "  estadístico acá NO lo apaga: sigue prendido por diseño. Lo que este\n"
            "  número sí dice es que con este universo y este período el poder no\n"
            "  alcanza para afirmar que aporta, ni para afirmar que resta.",
            fg=typer.colors.YELLOW,
        )
    typer.echo("")
    # acá el σ no se estima: la variante existe, así que sale del propio pareo
    deltas = [d for d in comparacion.pareo.deltas_r if d != 0.0]
    sigma = float(np.std(deltas, ddof=1)) if len(deltas) > 1 else None
    typer.echo(
        "\n".join(
            poder_lineas(
                resultado_base.rule_trades, spy=resultado_base.spy_data, sigma=sigma
            )
        )
    )


def _difieren_en_trailing(base, variante) -> bool:
    """¿La única capa que cambia entre las dos corridas es el trailing?"""

    def prendido(config) -> bool:
        trailing = config.exits.trailing_stop
        return trailing is not None and trailing.enabled

    return prendido(base) != prendido(variante)


def main() -> None:
    # Antes de cualquier salida: el informe escribe → y σ, y una consola cp1252
    # (el default de Windows) no los puede codificar. El fundamento de forzarlo
    # acá, en vez de dejarlo en manos del entorno, está en `consola.py`.
    forzar_utf8()
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
