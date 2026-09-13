"""La configuración se valida antes de descargar un solo dato, y con mensaje claro."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tradingbot.config import ConfigError, load_strategy

STRATEGIES = Path(__file__).resolve().parents[1] / "config" / "strategies"

BASE = {
    "name": "prueba",
    "universe": ["SPY"],
    "warmup_bars": 10,
    "indicators": {"ema_fast": {"type": "ema", "period": 20}},
    "entry": {"all": [{"left": "ema_fast", "op": ">", "right": "close"}]},
    "exits": {"hard_stop": {"mode": "atr", "multiple": 2.0}},
    "execution": {"commission_pct": 0.05, "slippage_pct": 0.05},
    "risk": {"position_sizing": {"risk_pct": 1.0}},
    "backtest": {"start": "2015-01-01", "end": "2020-12-31", "initial_cash": 10000},
}


def write(tmp_path: Path, **overrides) -> Path:
    data = {**BASE}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    path = tmp_path / "estrategia.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("template", sorted(STRATEGIES.glob("*.yaml")))
def test_las_plantillas_del_repo_son_validas(template):
    config = load_strategy(template)
    assert config.universe and config.entry


def test_carga_basica(tmp_path):
    config = load_strategy(write(tmp_path))
    assert config.name == "prueba"
    assert config.universe == ["SPY"]
    assert config.risk.position_sizing.on == "current_equity"
    assert config.source_path is not None


# --- los cuatro rechazos que pide la definición de terminado ---------------
def test_rechaza_indicador_inexistente(tmp_path):
    path = write(tmp_path, indicators={"x": {"type": "supertrend", "period": 10}})
    with pytest.raises(ConfigError, match="supertrend"):
        load_strategy(path)


def test_rechaza_operador_desconocido(tmp_path):
    path = write(tmp_path, entry={"all": [{"left": "close", "op": "toca", "right": 1}]})
    with pytest.raises(ConfigError, match="toca"):
        load_strategy(path)


def test_rechaza_in_sample_end_posterior_a_end(tmp_path):
    path = write(tmp_path, backtest={"in_sample_end": "2021-06-30"})
    with pytest.raises(ConfigError, match="in_sample_end"):
        load_strategy(path)


def test_rechaza_risk_pct_negativo(tmp_path):
    path = write(tmp_path, risk={"position_sizing": {"risk_pct": -1.0}})
    with pytest.raises(ConfigError, match="risk_pct"):
        load_strategy(path)


# --- otros errores frecuentes ---------------------------------------------
def test_rechaza_operando_inexistente(tmp_path):
    path = write(tmp_path, entry={"all": [{"left": "ema_lenta", "op": ">", "right": "close"}]})
    with pytest.raises(ConfigError, match="ema_lenta"):
        load_strategy(path)


def test_rechaza_parametro_de_indicador_desconocido(tmp_path):
    path = write(tmp_path, indicators={"ema_fast": {"type": "ema", "periodo": 20}})
    with pytest.raises(ConfigError, match="periodo"):
        load_strategy(path)


def test_rechaza_start_posterior_a_end(tmp_path):
    path = write(tmp_path, backtest={"start": "2021-01-01", "end": "2020-01-01"})
    with pytest.raises(ConfigError, match="anterior"):
        load_strategy(path)


def test_rechaza_universo_con_repetidos(tmp_path):
    path = write(tmp_path, universe=["SPY", "spy"])
    with pytest.raises(ConfigError, match="repetido"):
        load_strategy(path)


def test_rechaza_bollinger_sin_elegir_banda(tmp_path):
    """`bb` sin sufijo no existe: hay que decir bb.upper o bb.lower."""
    path = write(
        tmp_path,
        indicators={"bb": {"type": "bollinger", "period": 20}},
        entry={"all": [{"left": "close", "op": ">", "right": "bb"}]},
    )
    with pytest.raises(ConfigError, match="bb.upper"):
        load_strategy(path)


# --- lo que es del torneo (2C) se rechaza diciendo que lo es -----------------
@pytest.mark.parametrize(
    "bloque",
    [
        {"break_even": {"enabled": True, "trigger_r": 1.0}},
        {"reversal": {"mode": "count", "min_count": 2}},
        {"giveback": {"enabled": True}},
        {"time_stop": {"max_bars": 20}},
        {"market_regime": {"enabled": True}},
        {"event_risk": {"gap_down_pct": 5}},
    ],
)
def test_rechaza_capas_de_salida_de_la_tanda_2(tmp_path, bloque):
    path = write(tmp_path, exits={**BASE["exits"], **bloque})
    with pytest.raises(ConfigError, match="TODAVÍA NO ESTÁ IMPLEMENTADO"):
        load_strategy(path)


def test_el_trailing_ya_no_se_rechaza_pero_solo_en_chandelier(tmp_path):
    """El trailing salió de la lista de la tanda 2 al implementarse en la 2A.

    Los otros tres modos que el plan nombra (pct, structure, psar) siguen sin
    existir, así que se rechazan con el mismo criterio de siempre: un backtest que
    ignora media configuración miente.
    """
    path = write(
        tmp_path,
        exits={
            **BASE["exits"],
            "trailing_stop": {"mode": "chandelier", "multiple": 3.0, "activate_after_r": 1.0},
        },
    )
    config = load_strategy(path)
    assert config.exits.trailing_stop is not None
    assert config.exits.trailing_stop.multiple == 3.0
    assert config.exits.trailing_stop.activate_after_r == 1.0

    for modo in ("pct", "structure", "psar"):
        otro = write(
            tmp_path,
            exits={**BASE["exits"], "trailing_stop": {"mode": modo, "multiple": 3.0}},
        )
        with pytest.raises(ConfigError, match="no.*implementado"):
            load_strategy(otro)


def test_el_trailing_trae_los_defaults_del_plan(tmp_path):
    """3 x ATR desde el máximo, armado en +1R: es lo que dice PLAN.md."""
    path = write(tmp_path, exits={**BASE["exits"], "trailing_stop": {}})
    trailing = load_strategy(path).exits.trailing_stop
    assert (trailing.mode, trailing.multiple, trailing.activate_after_r) == (
        "chandelier",
        3.0,
        1.0,
    )


def test_el_riesgo_de_cartera_ya_no_se_rechaza(tmp_path):
    """Los cinco controles salieron de la lista de la tanda 2 al implementarse en 2B."""
    path = write(
        tmp_path,
        risk={
            **BASE["risk"],
            "max_portfolio_heat_r": 4.0,
            "max_per_group": {"sector": 2},
            "circuit_breaker": {"monthly_drawdown_pct": 6.0, "peak_drawdown_pct": 15.0},
        },
    )
    riesgo = load_strategy(path).risk
    assert riesgo.max_portfolio_heat_r == 4.0
    assert riesgo.max_per_group == {"sector": 2}
    assert riesgo.circuit_breaker.monthly_drawdown_pct == 6.0
    assert riesgo.circuit_breaker.peak_drawdown_pct == 15.0


def test_un_cortacircuito_vacio_es_un_error(tmp_path):
    """Un bloque sin ninguno de los dos topes no hace nada y hace creer que sí."""
    path = write(tmp_path, risk={**BASE["risk"], "circuit_breaker": {}})
    with pytest.raises(ConfigError, match="al menos uno"):
        load_strategy(path)


def test_un_tope_por_grupo_en_cero_es_un_error(tmp_path):
    path = write(tmp_path, risk={**BASE["risk"], "max_per_group": {"sector": 0}})
    with pytest.raises(ConfigError, match="no es un límite"):
        load_strategy(path)


def test_rechaza_entry_filters_de_la_tanda_2(tmp_path):
    path = write(tmp_path, entry_filters={"min_price": 10})
    with pytest.raises(ConfigError, match="TODAVÍA NO ESTÁ IMPLEMENTADO"):
        load_strategy(path)


def test_rechaza_salidas_parciales(tmp_path):
    path = write(
        tmp_path,
        exits={**BASE["exits"], "take_profit": {"mode": "rr", "ratio": 3, "partial": []}},
    )
    with pytest.raises(ConfigError, match="parciales"):
        load_strategy(path)


def test_archivo_inexistente(tmp_path):
    with pytest.raises(ConfigError, match="no existe"):
        load_strategy(tmp_path / "no_existe.yaml")


def test_yaml_roto(tmp_path):
    path = tmp_path / "roto.yaml"
    path.write_text("entry: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML inválido"):
        load_strategy(path)


# --- el umbral en el que risk_pct deja de decidir el tamaño ----------------
def test_umbral_de_sizing_es_risk_pct_sobre_max_position_pct(tmp_path):
    config = load_strategy(write(tmp_path, risk={"max_position_pct": 20.0}))
    assert config.sizing_threshold_pct == pytest.approx(5.0)

    config = load_strategy(
        write(tmp_path, risk={"position_sizing": {"risk_pct": 1.5}, "max_position_pct": 30.0})
    )
    assert config.sizing_threshold_pct == pytest.approx(5.0)  # 1.5/30 vuelve al mismo 5%


def test_avisa_cuando_un_stop_porcentual_deja_risk_pct_decorativo(tmp_path):
    """Con stop en %, la distancia se conoce al validar: el aviso sale de una."""
    path = write(
        tmp_path,
        exits={"hard_stop": {"mode": "pct", "pct": 3.0}},
        risk={"position_sizing": {"risk_pct": 1.0}, "max_position_pct": 20.0},
    )
    avisos = load_strategy(path).static_warnings()
    assert len(avisos) == 1
    assert "decorativo" in avisos[0] and "5.00%" in avisos[0]


def test_no_avisa_cuando_el_stop_es_mas_ancho_que_el_umbral(tmp_path):
    path = write(
        tmp_path,
        exits={"hard_stop": {"mode": "pct", "pct": 8.0}},
        risk={"position_sizing": {"risk_pct": 1.0}, "max_position_pct": 20.0},
    )
    assert load_strategy(path).static_warnings() == []


def test_el_aviso_es_aviso_y_no_error(tmp_path):
    """Hay configuraciones donde que el tope mande es intencional."""
    path = write(
        tmp_path,
        exits={"hard_stop": {"mode": "pct", "pct": 1.0}},
        risk={"position_sizing": {"risk_pct": 2.0}, "max_position_pct": 10.0},
    )
    config = load_strategy(path)  # no levanta
    assert config.static_warnings()


# --- registro de calibración ------------------------------------------------
def test_la_calibracion_por_defecto_es_la_v1(tmp_path):
    config = load_strategy(write(tmp_path))
    assert config.calibration.version == 1
    assert config.calibration.as_line() == "v1"


def test_la_calibracion_se_lee_del_yaml(tmp_path):
    path = write(
        tmp_path,
        calibration={"version": 3, "date": "2026-09-12", "changed": "stop 2 -> 2.5 ATR"},
    )
    calibracion = load_strategy(path).calibration
    assert calibracion.version == 3
    assert str(calibracion.fecha) == "2026-09-12"
    assert calibracion.as_line() == "v3 (2026-09-12) · stop 2 -> 2.5 ATR"


def test_subir_la_version_sin_decir_que_cambio_es_error(tmp_path):
    """Una versión nueva sin motivo no registra nada: es exactamente el problema."""
    path = write(tmp_path, calibration={"version": 2})
    with pytest.raises(ConfigError, match="no dice qué cambió"):
        load_strategy(path)


def test_las_plantillas_del_repo_declaran_su_calibracion():
    for template in sorted(STRATEGIES.glob("*.yaml")):
        calibracion = load_strategy(template).calibration
        if calibracion.version > 1:
            assert calibracion.changed, f"{template.name} no dice qué cambió"
            assert calibracion.fecha is not None


def test_la_calibracion_va_al_manifiesto_y_al_informe(tmp_path):
    """El registro no puede ser solo el fingerprint."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from fixtures.synthetic import synthetic_universe

    from tradingbot.backtest.engine import run_backtest
    from tradingbot.backtest.manifest import build_manifest
    from tradingbot.data.validate import validate_ohlcv
    from tradingbot.reporting.report import render_console

    config = load_strategy(STRATEGIES / "ema_cross.yaml")
    frames = {
        s: validate_ohlcv(df, s)
        for s, df in synthetic_universe(config.universe).items()
    }
    result = run_backtest(config, frames)
    manifest = build_manifest(config, frames, result.metrics)

    assert manifest["strategy"]["calibration"]["version"] == 3
    assert "trailing" in manifest["strategy"]["calibration"]["changed"]
    assert "Calibración   : v3" in render_console(result)
