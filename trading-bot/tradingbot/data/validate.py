"""Normalización y validación del OHLCV.

Un backtest sobre datos rotos da resultados perfectos y falsos, así que acá se
frena con un mensaje claro en vez de seguir. Este módulo es el único lugar donde
se normaliza lo que devuelve cada proveedor.
"""

from __future__ import annotations

import pandas as pd

from tradingbot.data.provider import OHLCV_COLUMNS

#: salto de precio de cierre a cierre que se considera imposible sin split
MAX_PRICE_JUMP = 0.50

#: fracción de días hábiles sin vela que se tolera (feriados de US ~3.6%)
MAX_MISSING_BUSINESS_DAYS_PCT = 0.15

#: hueco máximo, en días hábiles consecutivos, sin una sola vela
MAX_CONSECUTIVE_MISSING_DAYS = 10

#: tolerancia relativa al comparar dos precios de la misma vela entre sí.
#:
#: Hace falta porque el ajuste retroactivo multiplica cada columna por el mismo
#: factor pero con distinto orden de operaciones, así que un día que cerró
#: exactamente en su máximo (``close == high`` en el dato original) sale del
#: proveedor con ``close`` un ULP por encima de ``high``. Caso real: SPY
#: 2018-01-19 llega con ``close - high = 2.8e-14`` sobre precios de ~246, o sea
#: 1.2e-16 relativo. Con ~3800 velas por símbolo y 13 símbolos, cualquier día
#: que cierre en el máximo o abra en el mínimo dispara lo mismo.
#:
#: El valor es el punto medio geométrico entre los dos extremos que tiene que
#: separar:
#:
#: * **Piso (ruido de punto flotante).** Un ULP es ~2.2e-16 relativo; el ajuste
#:   encadena productos acumulados a lo largo de la serie, así que un techo
#:   generoso para el error acumulado son unos cientos de ULP, ~1e-13.
#: * **Techo (la inconsistencia genuina más chica).** Un feed roto que pone el
#:   cierre fuera del rango lo hace por al menos un tick de un centavo. Sobre un
#:   instrumento de $1000 —caro para lo que se opera acá— eso es 1e-5 relativo;
#:   sobre los ~$250 de SPY, 4e-5.
#:
#: 1e-9 queda cuatro órdenes de magnitud por encima del ruido y cuatro por
#: debajo del error más chico que vale la pena rechazar.
#:
#: **No se unifica con el ``TOLERANCE = 1e-6`` de ``data/cache.py``** aunque
#: ambos absorban ruido de punto flotante: aquel compara la misma vela bajada
#: dos veces para decidir si hubo reajuste retroactivo, y equivocarse cuesta una
#: descarga de más. Este decide si datos rotos entran a un backtest, y
#: equivocarse no cuesta nada visible: da un resultado perfecto y falso. Para el
#: que importa se toma el valor más ajustado que igual absorbe el ruido, no el
#: número que ya estaba escrito en otro lado.
PRICE_REL_TOL = 1e-9


class DataValidationError(ValueError):
    """Los datos no cumplen el contrato OHLCV y el backtest no puede seguir."""


class EmptySeriesError(DataValidationError):
    """El proveedor devolvió cero velas.

    Se separa del resto porque es el único fallo de validación que puede ser
    transitorio: el límite de tasa de Yahoo no llega como excepción de red sino
    como serie vacía. Quien reintente puede distinguirlo de una serie que está
    genuinamente rota, que va a estar igual de rota en el intento siguiente.
    """


def _mayor_que(izq: pd.Series, der: pd.Series) -> pd.Series:
    """``izq > der``, pero solo cuando la diferencia excede ``PRICE_REL_TOL``.

    El denominador es ``der``: en los casos que importan las dos series son
    iguales salvo el error de redondeo, así que cuál de las dos se use como
    escala no cambia nada.
    """
    return (izq - der) > PRICE_REL_TOL * der.abs()


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Lleva lo que devuelve un proveedor a la forma canónica.

    Minúsculas, índice tz-naive llamado ``date``, ordenado, columnas extra
    descartadas (``Dividends``, ``Stock Splits``, ...), dtypes fijados.
    """
    out = df.copy()
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]

    if not isinstance(out.index, pd.DatetimeIndex):
        date_col = next((c for c in ("date", "datetime", "time") if c in out.columns), None)
        if date_col is None:
            raise DataValidationError(
                "no hay índice de fechas ni columna 'date' en los datos recibidos"
            )
        out = out.set_index(pd.DatetimeIndex(pd.to_datetime(out[date_col])))
        out = out.drop(columns=[date_col])

    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    # velas diarias: el contrato es una fila por día, sin hora
    out.index = pd.DatetimeIndex(out.index).normalize()
    out.index.name = "date"

    missing = [c for c in OHLCV_COLUMNS if c not in out.columns]
    if missing:
        raise DataValidationError(f"faltan columnas obligatorias: {missing}")

    out = out[list(OHLCV_COLUMNS)]
    out = out.sort_index()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].astype("float64")
    return out


def validate_ohlcv(
    df: pd.DataFrame,
    symbol: str = "?",
    *,
    allow_zero_volume: bool = False,
    check_calendar: bool = True,
) -> pd.DataFrame:
    """Normaliza y valida. Devuelve el DataFrame canónico o levanta.

    Chequea: vacío, fechas duplicadas, NaN, ``high < low``, OHLC fuera del rango
    ``[low, high]``, precios <= 0, volumen negativo o cero, saltos de precio
    absurdos y velas faltantes en días hábiles.

    De todos esos, los únicos que necesitan ``PRICE_REL_TOL`` son los dos que
    comparan un precio de la vela contra otro precio de la misma vela, porque
    son los únicos donde el dato original tiene dos columnas que valen lo mismo
    y el ajuste retroactivo las separa. Los otros no:

    * **precio <= 0** compara contra una constante, no contra otro precio. Nada
      legítimo se apoya en el cero, y un precio que redondea a ~0 está roto de
      todas formas.
    * **volumen negativo o cero** es un entero y no lo toca el factor de ajuste
      de precios.
    * **salto de precio > 50%** es un umbral de criterio, no un punto donde dos
      números que deberían ser iguales se separan: nada hace que un movimiento
      real caiga exactamente en el 50%, así que un ULP de más o de menos ahí no
      cambia ninguna decisión.
    * **el calendario** compara fechas.
    """
    if df is None or len(df) == 0:
        # yfinance devuelve un DataFrame vacío sin error: vacío = error, siempre
        raise EmptySeriesError(f"{symbol}: el proveedor devolvió 0 velas")

    out = normalize_ohlcv(df)

    dupes = out.index[out.index.duplicated()]
    if len(dupes) > 0:
        raise DataValidationError(
            f"{symbol}: {len(dupes)} fechas duplicadas, p.ej. {_fmt_dates(dupes[:3])}"
        )

    nan_rows = out.index[out.isna().any(axis=1)]
    if len(nan_rows) > 0:
        raise DataValidationError(
            f"{symbol}: {len(nan_rows)} velas con NaN, p.ej. {_fmt_dates(nan_rows[:3])}"
        )

    # las cuatro comparaciones de precio contra precio van con PRICE_REL_TOL: en
    # una vela que abre en el mínimo o cierra en el máximo las dos columnas son
    # el mismo número antes de ajustar, y el ajuste las separa por un ULP
    bad = out.index[_mayor_que(out["low"], out["high"])]
    if len(bad) > 0:
        raise DataValidationError(
            f"{symbol}: {len(bad)} velas con high < low, p.ej. {_fmt_dates(bad[:3])}"
        )

    outside = out.index[
        _mayor_que(out["open"], out["high"])
        | _mayor_que(out["low"], out["open"])
        | _mayor_que(out["close"], out["high"])
        | _mayor_que(out["low"], out["close"])
    ]
    if len(outside) > 0:
        raise DataValidationError(
            f"{symbol}: {len(outside)} velas con open/close fuera del rango [low, high], "
            f"p.ej. {_fmt_dates(outside[:3])}"
        )

    nonpositive = out.index[(out[["open", "high", "low", "close"]] <= 0).any(axis=1)]
    if len(nonpositive) > 0:
        raise DataValidationError(
            f"{symbol}: {len(nonpositive)} velas con precio <= 0, "
            f"p.ej. {_fmt_dates(nonpositive[:3])}"
        )

    if (out["volume"] < 0).any():
        raise DataValidationError(f"{symbol}: hay volumen negativo")

    if not allow_zero_volume:
        zero_vol = out.index[out["volume"] == 0]
        if len(zero_vol) > 0:
            raise DataValidationError(
                f"{symbol}: {len(zero_vol)} velas con volumen cero, "
                f"p.ej. {_fmt_dates(zero_vol[:3])}"
            )

    jumps = out["close"].pct_change().abs()
    big = out.index[jumps > MAX_PRICE_JUMP]
    if len(big) > 0:
        raise DataValidationError(
            f"{symbol}: salto de precio > {MAX_PRICE_JUMP:.0%} sin split registrado en "
            f"{_fmt_dates(big[:3])} (¿serie sin ajustar?)"
        )

    if check_calendar and len(out) > 1:
        _check_calendar(out.index, symbol)

    out["volume"] = out["volume"].astype("int64")
    return out


def _check_calendar(index: pd.DatetimeIndex, symbol: str) -> None:
    expected = pd.bdate_range(index[0], index[-1])
    missing = expected.difference(index)
    if len(missing) == 0:
        return

    pct = len(missing) / len(expected)
    if pct > MAX_MISSING_BUSINESS_DAYS_PCT:
        raise DataValidationError(
            f"{symbol}: faltan {len(missing)} de {len(expected)} días hábiles "
            f"({pct:.1%}), muy por encima de los feriados esperados"
        )

    run, worst, worst_start = 0, 0, None
    for day in expected:
        if day in missing:
            run += 1
            if run > worst:
                worst, worst_start = run, day
        else:
            run = 0
    if worst > MAX_CONSECUTIVE_MISSING_DAYS:
        raise DataValidationError(
            f"{symbol}: hueco de {worst} días hábiles sin velas a partir de "
            f"{worst_start:%Y-%m-%d}"
        )


def _fmt_dates(idx) -> str:
    return ", ".join(pd.Timestamp(d).strftime("%Y-%m-%d") for d in idx)
