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


class DataValidationError(ValueError):
    """Los datos no cumplen el contrato OHLCV y el backtest no puede seguir."""


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
    """
    if df is None or len(df) == 0:
        # yfinance devuelve un DataFrame vacío sin error: vacío = error, siempre
        raise DataValidationError(f"{symbol}: el proveedor devolvió 0 velas")

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

    bad = out.index[out["high"] < out["low"]]
    if len(bad) > 0:
        raise DataValidationError(
            f"{symbol}: {len(bad)} velas con high < low, p.ej. {_fmt_dates(bad[:3])}"
        )

    outside = out.index[
        (out["open"] > out["high"])
        | (out["open"] < out["low"])
        | (out["close"] > out["high"])
        | (out["close"] < out["low"])
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
