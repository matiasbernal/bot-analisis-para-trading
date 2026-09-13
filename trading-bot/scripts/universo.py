#!/usr/bin/env python
"""¿Qué universo alcanza para que el torneo de capas decida algo?

El poder de medición sale de `backtest/poder.py` y depende de *n*, la cantidad
de trades. *n* no se elige: sale de cuántos símbolos, cuántos años y qué ritmo
de señales tiene la plantilla. Este script mide las tres cosas que se pueden
medir sin bajar datos nuevos y proyecta la cuarta:

1. **El ritmo de trades** de cada plantilla sobre los fixtures que hay, después
   del warmup (que es un costo fijo por símbolo y no por año: sobre 1250 velas
   se come el 16%, sobre 15 años el 5%).
2. **Cuántos trades da cada opción de universo** a ese ritmo.
3. **Qué capas quedan estimables** en cada opción, con el MDE recalculado por
   `poder.proyectar`.
4. **Cuántos trades necesita cada capa** para que su exigencia baje a un nivel
   dado, y cuántos símbolo-años son eso.

    python scripts/universo.py
    python scripts/universo.py --ritmo 2.4      # con el ritmo real, cuando se mida

**La etiqueta de alcance**: el ritmo, σ, la fracción por capa y el efecto
disponible salen de fixtures **sintéticos** (ver ESTADO.md §2). La aritmética
sobre *n* es exacta; los insumos valen lo que vale el fixture. El ritmo real se
mide bajando 3-4 símbolos de verdad, y por eso `--ritmo` existe: cuando haya
ese número, la tabla se rehace sin tocar el código.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from tradingbot.backtest.poder import (
    factor_z,
    poder_por_capa,
    proyectar,
    sigma_a_priori,
    trades_necesarios,
)
from tradingbot.config import StrategyConfig
from tradingbot.data.local import LocalCsvProvider

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / "tests" / "fixtures"
ESTRATEGIAS = RAIZ / "config" / "strategies"

#: velas por año de un mercado de acciones de EE.UU.
VELAS_POR_ANIO = 252


@dataclass(frozen=True)
class Opcion:
    """Un universo candidato, con lo que cuesta epistémicamente."""

    nombre: str
    simbolos: int
    #: símbolos que no tienen los 15 años completos, y cuántos años tienen
    historia_corta: dict[str, float]
    sesgo: str


#: Los sectoriales SPDR cotizan desde diciembre de 1998, menos XLRE, que se
#: escindió de XLF en octubre de 2015. IWM desde 2000, QQQ desde 1999, SPY desde
#: 1993. Con una ventana 2011-2025 el único que no la cubre entero es XLRE, y eso
#: cuesta cinco símbolo-años. **Verificar al bajar**: la primera vela de cada CSV
#: es el dato, esto es lo que se espera encontrar.
ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "SPY", "QQQ", "IWM"]

OPCIONES = [
    Opcion(
        nombre=f"{len(ETFS)} ETFs (sectoriales + SPY/QQQ/IWM)",
        simbolos=len(ETFS),
        historia_corta={"XLRE": 10.0},
        sesgo="casi nulo: un ETF no quiebra ni se deslista. Los sectoriales son "
        "los once de la clasificación GICS, no una selección",
    ),
    Opcion(
        nombre=f"{len(ETFS)} ETFs + 20 acciones líquidas",
        simbolos=len(ETFS) + 20,
        historia_corta={"XLRE": 10.0},
        sesgo="parcial: las 20 acciones se eligen hoy sabiendo que siguen "
        "cotizando. Las que quebraron no están en Yahoo",
    ),
    Opcion(
        nombre="40 acciones",
        simbolos=40,
        historia_corta={},
        sesgo="completo: 40 supervivientes elegidos con información posterior. "
        "El informe tiene que decirlo en cada corrida",
    ),
]

#: exigencias de referencia: qué fracción del efecto disponible tiene que
#: capturar la capa para que el resultado se distinga del ruido
EXIGENCIAS = (0.66, 0.50, 0.33)


# --- 1. ritmo de trades ----------------------------------------------------
@dataclass(frozen=True)
class Ritmo:
    plantilla: str
    universo: str
    simbolos: int
    velas_utiles: int
    simbolo_anios: float
    trades: int
    señales_rechazadas: int

    @property
    def por_simbolo_anio(self) -> float:
        return self.trades / self.simbolo_anios if self.simbolo_anios else 0.0


def corrida(plantilla: Path, datos: Path, simbolos: list[str] | None = None, *, cupo: int | None = None):
    """Corre una plantilla sobre un directorio de CSV. ``[]`` toma todo el directorio.

    ``cupo`` pisa ``risk.max_open_positions``: sirve para medir cuántas señales
    hubo de verdad, aparte de cuántas se pudieron tomar.
    """
    from tradingbot.backtest.engine import run_backtest
    from tradingbot.config import load_universe

    config = yaml.safe_load(plantilla.read_text(encoding="utf-8"))
    if cupo is not None:
        config["risk"] = {**config["risk"], "max_open_positions": cupo}
    if simbolos == []:
        simbolos = sorted(p.stem for p in datos.glob("*.csv"))
    elif simbolos is None:
        simbolos = config["universe"]
    config["universe"] = simbolos
    strategy = StrategyConfig(**config)
    provider = LocalCsvProvider(datos)
    frames = {
        s: provider.get_ohlcv(
            s, start=strategy.backtest.start, end=strategy.backtest.end, interval="1d"
        )
        for s in simbolos
    }
    grupos = load_universe(RAIZ / "config" / "universe.yaml")
    resultado = run_backtest(strategy, frames, spy_frame=frames.get("SPY"), groups=grupos)
    return resultado, frames, strategy


def medir_ritmo(plantilla: Path, universo: str, datos: Path, simbolos) -> tuple[Ritmo, object]:
    """Trades por símbolo-año **útil**, o sea descontando el warmup de cada símbolo.

    El warmup se descuenta una vez por símbolo y no una vez por año: es lo que
    hace que la misma plantilla rinda más sobre 15 años que sobre 5, sin que
    cambie nada de la plantilla.
    """
    resultado, frames, strategy = corrida(plantilla, datos, simbolos)
    utiles = sum(max(0, len(df) - strategy.warmup_bars) for df in frames.values())
    ritmo = Ritmo(
        plantilla=plantilla.stem,
        universo=universo,
        simbolos=len(frames),
        velas_utiles=utiles,
        simbolo_anios=utiles / VELAS_POR_ANIO,
        trades=len(resultado.rule_trades),
        señales_rechazadas=len(resultado.rejections),
    )
    return ritmo, resultado


# --- 2. proyección ---------------------------------------------------------
def simbolo_anios_utiles(opcion: Opcion, anios: float, warmup_bars: int) -> float:
    """Años netos del universo: historia disponible menos el warmup de cada símbolo."""
    warmup_anios = warmup_bars / VELAS_POR_ANIO
    total = 0.0
    for i in range(opcion.simbolos):
        disponibles = anios
        if i < len(opcion.historia_corta):
            disponibles = list(opcion.historia_corta.values())[i]
        total += max(0.0, disponibles - warmup_anios)
    return total


def n_esperado(opcion: Opcion, anios: float, ritmo: float, warmup_bars: int) -> int:
    return int(round(simbolo_anios_utiles(opcion, anios, warmup_bars) * ritmo))


def techo_por_cupo(max_open: int, duracion_bars: float, anios: float) -> int:
    """Trades que el cupo de cartera deja tomar, **haya los símbolos que haya**.

    Cinco posiciones abiertas a la vez, cada una ocupando su lugar ``duracion``
    velas, dan como mucho ``5 / duración`` trades por año. Ampliar el universo
    sube las señales pero no sube eso: pasado cierto tamaño, los símbolos nuevos
    solo agregan señales rechazadas. Es un techo **optimista**: supone que las
    señales llegan repartidas, y las de un universo correlacionado llegan juntas.
    """
    if duracion_bars <= 0:
        return 0
    return int(round(max_open / (duracion_bars / VELAS_POR_ANIO) * anios))


def n_para_exigencia(fila, exigencia: float) -> int:
    """Trades que hacen falta para que la capa se vea capturando ``exigencia`` de lo disponible."""
    if fila.efecto_disponible <= 0:
        return 0
    return trades_necesarios(
        exigencia * fila.efecto_disponible, sigma=fila.sigma, fraccion=fila.fraccion
    )


# --- 3. tamaño en disco ----------------------------------------------------
def bytes_por_fila(decimales: int | None) -> float:
    """Mide el ancho real de una fila de CSV, con y sin redondeo.

    No es un detalle: un float64 de Yahoo se escribe con 17 dígitos
    (``88.11726379394531``) y ocupa el doble que el mismo precio con cuatro
    decimales. La diferencia entre commitear 6 MB y commitear 13 MB es esa.
    """
    fechas = pd.bdate_range("2010-01-04", periods=500, name="date")
    # precios con mantisa "fea", como los ajustados de Yahoo
    cierres = pd.Series([100 * (1 + i) ** 0.5 / 3 for i in range(len(fechas))], index=fechas)
    df = pd.DataFrame(
        {
            "open": cierres * 0.995,
            "high": cierres * 1.013,
            "low": cierres * 0.987,
            "close": cierres,
            "volume": pd.Series(98_765_432, index=fechas, dtype="int64"),
        }
    )
    if decimales is not None:
        df = df.round(decimales)
    texto = df.to_csv(index_label="date")
    return (len(texto.encode("utf-8")) - len(texto.splitlines()[0]) - 1) / len(df)


def filas_totales(opcion: Opcion, anios: float) -> int:
    total = 0.0
    for i in range(opcion.simbolos):
        disponibles = anios
        if i < len(opcion.historia_corta):
            disponibles = list(opcion.historia_corta.values())[i]
        total += disponibles * VELAS_POR_ANIO
    return int(round(total))


# --- salida ----------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anios", type=float, default=15.0, help="Años de historia (default 15)")
    parser.add_argument(
        "--ritmo",
        type=float,
        default=None,
        help="Trades por símbolo-año útil. Default: el medido sobre los fixtures",
    )
    parser.add_argument(
        "--plantilla",
        type=Path,
        default=ESTRATEGIAS / "ema_cross.yaml",
        help="Plantilla de la que sale el poder por capa",
    )
    args = parser.parse_args(argv)

    universos = {
        "sintético independiente (4)": (FIXTURES, None),
        "sintético correlacionado (10)": (FIXTURES / "correlated", []),
    }
    plantillas = sorted(ESTRATEGIAS.glob("*.yaml"))

    print("=" * 94)
    print("1. RITMO DE TRADES MEDIDO — sobre los fixtures que hay (sintéticos, ver ESTADO.md §2)")
    print("=" * 94)
    print("  plantilla                      universo                 símb  símb-año  trades  "
          "t/s-año  rech.")
    ritmos: dict[str, Ritmo] = {}
    for plantilla in plantillas:
        for nombre, (datos, simbolos) in universos.items():
            config = yaml.safe_load(plantilla.read_text(encoding="utf-8"))
            pedidos = sorted(p.stem for p in datos.glob("*.csv")) if simbolos == [] else None
            if pedidos is None:
                pedidos = config["universe"]
            provider = LocalCsvProvider(datos)
            if not all(provider.has(s) for s in pedidos):
                continue
            ritmo, _ = medir_ritmo(plantilla, nombre, datos, simbolos)
            ritmos[f"{plantilla.stem}|{nombre}"] = ritmo
            print(
                f"  {ritmo.plantilla:<30} {ritmo.universo:<24} {ritmo.simbolos:>4}  "
                f"{ritmo.simbolo_anios:>8.1f}  {ritmo.trades:>6}  {ritmo.por_simbolo_anio:>7.2f}  "
                f"{ritmo.señales_rechazadas:>5}"
            )
    print("\n  't/s-año' descuenta el warmup: 200 velas por símbolo, una vez, no una vez por año.")
    print("  'rech.' son señales que el cupo de cartera no dejó tomar. Sobre un universo más")
    print("  grande ese número crece y el ritmo por símbolo-año baja: no es lineal en símbolos.")

    base = ritmos.get(f"{args.plantilla.stem}|sintético correlacionado (10)")
    if base is None:
        print(f"\nno se pudo medir {args.plantilla.stem} sobre el universo correlacionado")
        return 1
    ritmo_usado = args.ritmo if args.ritmo is not None else base.por_simbolo_anio
    fuente_ritmo = "pasado por --ritmo" if args.ritmo else f"medido: {base.plantilla}, sintético"

    resultado, _, strategy = corrida(args.plantilla, FIXTURES / "correlated", [])
    trades = resultado.rule_trades
    sigma = sigma_a_priori(trades)
    filas = poder_por_capa(trades, spy=resultado.spy_data, sigma=sigma)

    duracion = float(pd.Series([t.bars_held for t in trades]).mean())
    cupo = strategy.risk.max_open_positions
    techo = techo_por_cupo(cupo, duracion, args.anios)

    print("")
    print("=" * 94)
    print(f"2. LAS OPCIONES DE UNIVERSO — {args.anios:.0f} años, {ritmo_usado:.2f} trades por "
          f"símbolo-año ({fuente_ritmo})")
    print("=" * 94)
    sin_cupo, _, _ = corrida(args.plantilla, FIXTURES / "correlated", [], cupo=99)
    tomados, habia = len(trades), len(sin_cupo.rule_trades)
    print(f"  El cupo de cartera pone un techo que no depende del universo: {cupo} posiciones")
    print(f"  simultáneas, {duracion:.0f} velas de duración media, dan {techo / args.anios:.0f} "
          f"trades por año = {techo} en {args.anios:.0f} años,")
    print("  haya 13 símbolos o 40. Y es un techo optimista: supone señales repartidas en el")
    print("  tiempo, y las de un universo correlacionado llegan juntas. Medido sobre el fixture")
    print(f"  correlacionado (10 símbolos): con cupo {cupo} se tomaron {tomados} trades y sin cupo "
          f"habría habido {habia}")
    print(f"  ({100 * (habia - tomados) / habia:.0f}% perdido con 10 símbolos, lejos del techo "
          "por carga media). Esa fracción")
    print("  crece con el universo y no se puede medir con los fixtures que hay: por eso las dos")
    print("  columnas de abajo son cota superior, y más floja cuanto más grande el universo.")
    print("")
    print("  opción                                símb  símb-año útil   señales   n con cupo   "
          "capas estim.")
    proyecciones: dict[str, tuple[int, list]] = {}
    for opcion in OPCIONES:
        señales = n_esperado(opcion, args.anios, ritmo_usado, strategy.warmup_bars)
        n = min(señales, techo)
        proyectadas = proyectar(filas, n)
        estimables = [f for f in proyectadas if f.medible]
        proyecciones[opcion.nombre] = (n, proyectadas)
        marca = "  (el cupo corta)" if n < señales else ""
        print(
            f"  {opcion.nombre:<36} {opcion.simbolos:>4}  "
            f"{simbolo_anios_utiles(opcion, args.anios, strategy.warmup_bars):>12.0f}   "
            f"{señales:>7}   {n:>10}   {len(estimables)} de {len(proyectadas)}{marca}"
        )
    print("")
    print("  costo epistémico de cada una:")
    for opcion in OPCIONES:
        print(f"    {opcion.nombre:<36} {opcion.sesgo}")
        for simbolo, anios_reales in opcion.historia_corta.items():
            print(
                f"    {'':<36} ojo: {simbolo} cotiza desde 2015 → {anios_reales:.0f} años, "
                f"no {args.anios:.0f}"
            )

    print("")
    print("=" * 94)
    print("3. QUÉ DECIDE CADA OPCIÓN — una fila por capa y por universo")
    print("=" * 94)
    for opcion in OPCIONES:
        n, proyectadas = proyecciones[opcion.nombre]
        print(f"\n  {opcion.nombre}  ·  n = {n} trades")
        print("    capa             afect    f     MDE/afect  disponible  veredicto")
        for fila in proyectadas:
            print(
                f"    {fila.capa:<15} {fila.n_afectados:>4}  {fila.fraccion:5.2f}  "
                f"{fila.mde_afectado:8.2f}R  {fila.efecto_disponible:8.2f}R  {fila.veredicto}"
            )

    print("")
    print("=" * 94)
    print("4. CUÁNTOS TRADES PIDE CADA CAPA — y cuántos símbolo-años son, a este ritmo")
    print("=" * 94)
    print("  Leer así: 'exigencia 33%' es que la capa se vea capturando un tercio del efecto")
    print("  que tiene disponible. Cuanto más baja la exigencia, más creíble el resultado y")
    print(f"  más trades pide (el MDE va con 1/√(f·n), así que bajar la exigencia a la mitad")
    print("  cuadruplica los trades).")
    print("")
    print("  Y va por duplicado, porque f, σ y el efecto disponible salen del fixture: los dos")
    print("  universos sintéticos dan respuestas distintas y esa distancia es la incertidumbre")
    print("  real de esta tabla, más grande que cualquier decimal.")
    encabezado = "  capa             f      disp   " + "".join(
        f"  n({e:.0%})  símb-año" for e in EXIGENCIAS
    )
    for nombre, (datos, simbolos) in universos.items():
        provider = LocalCsvProvider(datos)
        pedidos = (
            sorted(p.stem for p in datos.glob("*.csv"))
            if simbolos == []
            else yaml.safe_load(args.plantilla.read_text(encoding="utf-8"))["universe"]
        )
        if not all(provider.has(s) for s in pedidos):
            continue
        resultado_base, _, _ = corrida(args.plantilla, datos, simbolos)
        trades_base = resultado_base.rule_trades
        sigma_base = sigma_a_priori(trades_base)
        filas_base = poder_por_capa(trades_base, spy=resultado_base.spy_data, sigma=sigma_base)
        print(f"\n  insumos del fixture {nombre} · n hoy = {len(trades_base)} · σ = {sigma_base:.2f}R")
        print(encabezado)
        for fila in filas_base:
            linea = f"  {fila.capa:<15} {fila.fraccion:5.2f}  {fila.efecto_disponible:5.2f}R  "
            for exigencia in EXIGENCIAS:
                n = n_para_exigencia(fila, exigencia)
                linea += f"  {n:>6}  {n / ritmo_usado:>8.0f}" if n else f"  {'—':>6}  {'—':>8}"
            print(linea)
    print("")
    print(f"  z(α=5%, potencia=80%) = {factor_z():.3f} · σ = {sigma:.2f}R")
    print(f"  A {ritmo_usado:.2f} trades por símbolo-año, 15 años de historia rinden "
          f"{15 * ritmo_usado:.1f} trades por símbolo:")
    for simbolos in (13, 33, 40):
        print(f"    {simbolos:>3} símbolos → {int(round(simbolos * 15 * ritmo_usado)):>5} trades")

    print("")
    print("=" * 94)
    print("5. TAMAÑO EN DISCO — lo que se commitea")
    print("=" * 94)
    ancho_crudo = bytes_por_fila(None)
    ancho_redondeado = bytes_por_fila(4)
    print(f"  ancho de una fila: {ancho_crudo:.0f} bytes con el float64 entero de Yahoo, "
          f"{ancho_redondeado:.0f} bytes redondeada a 4 decimales")
    print("  opción                                 filas    CSV crudo   CSV a 4 decimales")
    for opcion in OPCIONES:
        filas_csv = filas_totales(opcion, args.anios)
        print(
            f"  {opcion.nombre:<36} {filas_csv:>8}   {filas_csv * ancho_crudo / 1e6:>8.1f} MB   "
            f"{filas_csv * ancho_redondeado / 1e6:>12.1f} MB"
        )
    reales = sorted(FIXTURES.rglob("*.csv"))
    if reales:
        total = sum(p.stat().st_size for p in reales)
        filas_hoy = sum(sum(1 for _ in p.open(encoding="utf-8")) - 1 for p in reales)
        print(
            f"\n  hoy en tests/fixtures/: {len(reales)} CSV, {filas_hoy} filas, "
            f"{total / 1e6:.2f} MB ({total / filas_hoy:.0f} bytes por fila, sintéticos "
            "redondeados a 4 decimales)"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
