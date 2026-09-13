#!/usr/bin/env python
"""Baja datos reales a ``tests/fixtures/`` para usarlos como fixture.

Se corre donde haya salida a Yahoo (tu máquina, o el sandbox si la política de
red del entorno lo permite) y el resultado se commitea:

    python scripts/fetch_fixture.py SPY AAPL
    python scripts/fetch_fixture.py --years 15 --out tests/fixtures/etfs XLK XLF ...

Hasta que existan esos CSV, los tests que los usan se saltean con el motivo.
No bloquean nada.

Cuatro cosas que hace y que un bucle de descarga ingenuo no hace:

* **Refresca sin romper el ajuste retroactivo.** Los precios ajustados cambian
  hacia atrás en cada dividendo o split. Si el CSV ya existe, se bajan las
  últimas ``OVERLAP_BARS`` velas y se comparan con lo que hay; si difieren más
  de ``TOLERANCE`` relativo, se rebaja el histórico completo en vez de pegar
  barras nuevas sobre una serie vieja. La comparación es la misma de
  ``data/cache.py`` (``ParquetCache.overlap_differs``), no una copia.
* **Escribe un sidecar JSON** por símbolo con ``provider``, ``fetched_at``,
  ``adjusted``, ``rows``, ``first`` y ``last``. Un CSV sin sidecar no dice de
  dónde vino ni si está ajustado por dividendos, y Yahoo y Stooq no son
  comparables.
* **Respeta el límite de tasa**: descarga secuencial, pausa de ``--pausa``
  segundos entre símbolos (nunca ``threads=True``), y reintentos con espera que
  se duplica, porque el 429 de Yahoo llega como serie vacía.
* **Vacío = error, siempre.** Una serie vacía no se escribe: cuenta como falla
  del símbolo y el script termina con código distinto de cero.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from tradingbot.data.cache import OVERLAP_BARS, CacheMeta, ParquetCache
from tradingbot.data.provider import Provider
from tradingbot.data.validate import validate_ohlcv

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

#: pausa entre símbolos. Yahoo tolera ~1 pedido cada 0.5 s sostenido
PAUSA_DEFAULT = 0.5

#: reintentos por símbolo ante fallo transitorio (429, corte de red)
REINTENTOS_DEFAULT = 3

#: espera del primer reintento; se duplica en cada uno
ESPERA_INICIAL = 2.0


def sidecar_path(csv_path: Path) -> Path:
    """El JSON que acompaña a cada CSV: ``SPY.csv`` -> ``SPY.json``."""
    return csv_path.with_suffix(".json")


def leer_csv(path: Path, symbol: str) -> pd.DataFrame:
    """El CSV que ya está en disco, validado.

    ``check_calendar=False``: un fixture puede estar recortado a propósito y eso
    no es un error de datos; lo que importa acá es el contrato de columnas.
    """
    return validate_ohlcv(pd.read_csv(path), symbol, check_calendar=False)


def con_reintentos(
    descargar,
    *,
    reintentos: int = REINTENTOS_DEFAULT,
    espera: float = ESPERA_INICIAL,
    aviso=lambda mensaje: print(mensaje, file=sys.stderr),
) -> pd.DataFrame:
    """Llama a ``descargar()`` hasta ``reintentos`` veces, duplicando la espera.

    El límite de tasa de Yahoo no llega como excepción de red sino como serie
    vacía, que ``validate_ohlcv`` convierte en ``DataValidationError``. Es
    indistinguible de un símbolo inexistente, así que se reintenta igual: si de
    verdad no existe, los tres intentos fallan y el error queda en pie.
    """
    ultimo: Exception | None = None
    for intento in range(1, reintentos + 1):
        try:
            return descargar()
        except Exception as exc:  # noqa: BLE001 - el motivo se reporta, no el traceback
            ultimo = exc
            if intento < reintentos:
                aviso(f"    intento {intento}/{reintentos} falló ({exc}); reintento en {espera:.0f}s")
                time.sleep(espera)
                espera *= 2
    assert ultimo is not None
    raise ultimo


def refrescar(
    provider: Provider,
    symbol: str,
    path: Path,
    *,
    start,
    end,
    interval: str = "1d",
    reintentos: int = REINTENTOS_DEFAULT,
) -> tuple[pd.DataFrame, str]:
    """Devuelve la serie actualizada y en qué estado quedó.

    Tres caminos: no había CSV (descarga completa), el solape coincide (se pegan
    las velas nuevas) o el solape difiere (hubo reajuste retroactivo y se rebaja
    el histórico entero).
    """

    def completa() -> pd.DataFrame:
        return provider.get_ohlcv(symbol, start=str(start), end=str(end), interval=interval)

    if not path.is_file():
        return con_reintentos(completa, reintentos=reintentos), "nuevo"

    cached = leer_csv(path, symbol)
    desde = cached.index[max(0, len(cached) - OVERLAP_BARS)]
    recientes = con_reintentos(
        lambda: provider.get_ohlcv(symbol, start=desde, end=str(end), interval=interval),
        reintentos=reintentos,
    )

    if ParquetCache.overlap_differs(cached, recientes):
        return con_reintentos(completa, reintentos=reintentos), "rebajado (reajuste retroactivo)"

    nuevas = recientes[~recientes.index.isin(cached.index)]
    if nuevas.empty:
        return cached, "sin cambios"
    return pd.concat([cached, nuevas]).sort_index(), f"+{len(nuevas)} velas"


def escribir(
    path: Path, df: pd.DataFrame, *, provider: Provider, interval: str = "1d"
) -> CacheMeta:
    """Guarda el CSV y su sidecar. El sidecar tiene el mismo esquema que el cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index_label="date")
    meta = CacheMeta(
        provider=provider.name,
        interval=interval,
        adjusted=provider.adjusted,
        rows=len(df),
        first=df.index[0].strftime("%Y-%m-%d"),
        last=df.index[-1].strftime("%Y-%m-%d"),
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    sidecar_path(path).write_text(
        json.dumps(asdict(meta), indent=2, sort_keys=True), encoding="utf-8"
    )
    return meta


def bajar_universo(
    provider: Provider,
    symbols: list[str],
    out: Path,
    *,
    start,
    end,
    interval: str = "1d",
    pausa: float = PAUSA_DEFAULT,
    reintentos: int = REINTENTOS_DEFAULT,
    dormir=time.sleep,
    escribir_salida=print,
) -> int:
    """Descarga secuencial de ``symbols``. Devuelve cuántos fallaron."""
    out.mkdir(parents=True, exist_ok=True)
    fallaron = 0
    for posicion, simbolo in enumerate(symbols):
        symbol = simbolo.upper()
        path = out / f"{symbol}.csv"
        if posicion:
            dormir(pausa)  # límite de tasa: secuencial y espaciado, nunca en paralelo
        try:
            df, estado = refrescar(
                provider,
                symbol,
                path,
                start=start,
                end=end,
                interval=interval,
                reintentos=reintentos,
            )
        except Exception as exc:  # noqa: BLE001 - acá queremos el motivo, no el traceback
            print(f"  ! {symbol}: {exc}", file=sys.stderr)
            fallaron += 1
            continue
        escribir(path, df, provider=provider, interval=interval)
        escribir_salida(
            f"  ✓ {symbol}: {len(df)} velas {df.index[0]:%Y-%m-%d} → "
            f"{df.index[-1]:%Y-%m-%d} [{estado}] -> {path}"
        )
    return fallaron


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+", help="Símbolos a bajar (p.ej. SPY AAPL)")
    parser.add_argument("--years", type=int, default=3, help="Años de historia (default 3)")
    parser.add_argument(
        "--out", type=Path, default=FIXTURES, help="Directorio destino (default tests/fixtures)"
    )
    parser.add_argument(
        "--provider", choices=["yahoo", "stooq"], default="yahoo", help="Fuente de datos"
    )
    parser.add_argument(
        "--start", help="Fecha inicial YYYY-MM-DD (pisa --years; fija el fixture en el tiempo)"
    )
    parser.add_argument("--end", help="Fecha final YYYY-MM-DD (default: hoy)")
    parser.add_argument(
        "--pausa",
        type=float,
        default=PAUSA_DEFAULT,
        help=f"Segundos entre símbolos (default {PAUSA_DEFAULT}; no lo bajes)",
    )
    parser.add_argument(
        "--reintentos",
        type=int,
        default=REINTENTOS_DEFAULT,
        help=f"Intentos por símbolo ante fallo transitorio (default {REINTENTOS_DEFAULT})",
    )
    args = parser.parse_args(argv)

    if args.provider == "yahoo":
        from tradingbot.data.yahoo import YahooProvider

        provider: Provider = YahooProvider()
    else:
        from tradingbot.data.stooq import StooqProvider

        provider = StooqProvider()

    end = date.fromisoformat(args.end) if args.end else date.today()
    start = (
        date.fromisoformat(args.start)
        if args.start
        else end - timedelta(days=int(args.years * 365.25) + 5)
    )

    print(
        f"{len(args.symbols)} símbolo(s) de {provider.name}, {start} → {end}, "
        f"pausa {args.pausa}s, {args.reintentos} intento(s) por símbolo"
    )
    failed = bajar_universo(
        provider,
        args.symbols,
        args.out,
        start=start,
        end=end,
        pausa=args.pausa,
        reintentos=args.reintentos,
    )

    if failed:
        print(
            f"\n{failed} símbolo(s) fallaron. Si estás en un entorno sin salida a Yahoo, "
            "corré esto en tu máquina.",
            file=sys.stderr,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
