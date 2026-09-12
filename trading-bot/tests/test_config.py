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


# --- lo que es de la tanda 2 se rechaza diciendo que es de la tanda 2 ------
@pytest.mark.parametrize(
    "bloque",
    [
        {"trailing_stop": {"mode": "chandelier", "multiple": 3.0}},
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
    with pytest.raises(ConfigError, match="tanda 1"):
        load_strategy(path)


def test_rechaza_riesgo_de_cartera_de_la_tanda_2(tmp_path):
    path = write(tmp_path, risk={"max_portfolio_heat_r": 4.0})
    with pytest.raises(ConfigError, match="tanda 1"):
        load_strategy(path)


def test_rechaza_entry_filters_de_la_tanda_2(tmp_path):
    path = write(tmp_path, entry_filters={"min_price": 10})
    with pytest.raises(ConfigError, match="tanda 1"):
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
