"""Carga y validación de la configuración (YAML -> pydantic).

Todo lo que el usuario toca vive en el YAML de estrategia. Acá se valida
**antes de descargar un solo dato**: que cada ``type:`` exista en el registry de
indicadores, que cada operador exista, que cada operando se pueda resolver, y
que las fechas y los porcentajes tengan sentido. Un KeyError a los diez minutos
de backtest no es un mensaje de error.

Lo que todavía no está implementado (tanda 2: trailing, break-even, reversión,
giveback, time stop, régimen, earnings, riesgo de cartera) se rechaza con un
mensaje que dice explícitamente que es de la tanda 2, en vez de ignorarse en
silencio y hacer creer que el backtest lo tuvo en cuenta.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from tradingbot.data.provider import OHLCV_COLUMNS
from tradingbot.indicators.registry import (
    IndicatorError,
    indicator_outputs,
    primary_output,
    validate_params,
)
from tradingbot.strategy.conditions import OPERATORS


class ConfigError(ValueError):
    """La configuración no es válida. El mensaje dice qué y dónde."""


#: bloques previstos en el plan pero que son de la tanda 2 en adelante
_TANDA_2 = {
    "trailing_stop": "trailing stop (Fase 3)",
    "break_even": "break-even (Fase 3)",
    "reversal": "salida por reversión (Fase 3)",
    "giveback": "giveback (Fase 3)",
    "time_stop": "time stop (Fase 3)",
    "market_regime": "filtro de régimen de mercado (Fase 3)",
    "event_risk": "riesgo de eventos / earnings (Fase 3)",
}

_RISK_TANDA_2 = {
    "max_portfolio_heat_r": "heat de cartera (Fase 3)",
    "max_per_group": "límite por grupo (Fase 3)",
    "circuit_breaker": "cortacircuito por drawdown (Fase 3)",
}


def _reject_future(data: Mapping[str, Any], table: Mapping[str, str], where: str) -> None:
    for key, label in table.items():
        if key in data:
            raise ValueError(
                f"{where}: '{key}' es {label}; no está implementado en la tanda 1. "
                "Sacalo del YAML o esperá la tanda 2."
            )


class IndicatorSpec(BaseModel):
    """``ema_fast: {type: ema, source: close, period: 20}``."""

    model_config = ConfigDict(extra="forbid")

    type: str
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _split_params(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and "params" not in data:
            data = dict(data)
            type_ = data.pop("type", None)
            if type_ is None:
                raise ValueError("un indicador necesita 'type'")
            return {"type": type_, "params": data}
        return data

    @model_validator(mode="after")
    def _check_registry(self) -> "IndicatorSpec":
        try:
            validate_params(self.type, self.params)
        except IndicatorError as exc:
            raise ValueError(str(exc)) from None
        return self


class PositionSizing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["risk_pct"] = "risk_pct"
    risk_pct: float = Field(1.0, gt=0, le=100)
    on: Literal["current_equity", "initial_equity"] = "current_equity"

    @model_validator(mode="before")
    @classmethod
    def _fix_yaml_on_key(cls, data: Any) -> Any:
        # YAML 1.1: la clave `on:` se parsea como el booleano True. El plan la
        # escribe sin comillas, así que se acepta tal cual.
        if isinstance(data, Mapping) and True in data:
            data = {("on" if k is True else k): v for k, v in data.items()}
        return data


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_sizing: PositionSizing = Field(default_factory=PositionSizing)
    max_position_pct: float = Field(20.0, gt=0, le=100)
    max_open_positions: int = Field(5, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _reject_portfolio_risk(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            _reject_future(data, _RISK_TANDA_2, "risk")
        return data


class HardStop(BaseModel):
    """El piso que no se negocia. Define 1R y de ahí sale el tamaño."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["atr", "pct"] = "atr"
    multiple: float = Field(2.0, gt=0)
    pct: float | None = Field(None, gt=0)
    atr_period: int = Field(14, ge=1)

    @model_validator(mode="after")
    def _check_mode(self) -> "HardStop":
        if self.mode == "pct" and self.pct is None:
            raise ValueError("hard_stop mode 'pct' necesita 'pct' (porcentaje de la entrada)")
        return self


class TakeProfit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["rr"] = "rr"
    ratio: float = Field(3.0, gt=0)
    enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def _reject_partials(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and "partial" in data:
            raise ValueError(
                "take_profit: las salidas parciales son de la tanda 2 (Fase 3)"
            )
        return data


class ExitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: dict[str, Any] | None = None
    hard_stop: HardStop = Field(default_factory=HardStop)
    take_profit: TakeProfit | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_future_layers(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            _reject_future(data, _TANDA_2, "exits")
        return data


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_on: Literal["close"] = "close"
    fill_on: Literal["next_open"] = "next_open"
    commission_pct: float = Field(0.0, ge=0)
    slippage_pct: float = Field(0.0, ge=0)


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date | None = None
    end: date | None = None
    initial_cash: float = Field(10_000.0, gt=0)
    in_sample_end: date | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> "BacktestConfig":
        if self.start and self.end and self.start >= self.end:
            raise ValueError(f"backtest: start ({self.start}) debe ser anterior a end ({self.end})")
        if self.in_sample_end and self.end and self.in_sample_end > self.end:
            raise ValueError(
                f"backtest: in_sample_end ({self.in_sample_end}) no puede ser posterior "
                f"a end ({self.end})"
            )
        if self.in_sample_end and self.start and self.in_sample_end <= self.start:
            raise ValueError(
                f"backtest: in_sample_end ({self.in_sample_end}) debe ser posterior "
                f"a start ({self.start})"
            )
        return self


class Calibration(BaseModel):
    """Qué versión de esta estrategia es, y qué cambió respecto de la anterior.

    Sin esto, dos informes de la misma plantilla con parámetros distintos se ven
    iguales: mismo nombre, y la única diferencia es un fingerprint que nadie
    compara de memoria. Subir ``version`` sin decir qué cambió no sirve, así que
    es un error.
    """

    # el campo se llama `fecha` porque un campo llamado `date` taparía al tipo
    # `date` al evaluar las anotaciones; en el YAML se escribe `date:`
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version: int = Field(1, ge=1)
    fecha: date | None = Field(None, alias="date")
    changed: str = ""

    @model_validator(mode="after")
    def _exige_motivo(self) -> "Calibration":
        if self.version > 1 and not self.changed.strip():
            raise ValueError(
                f"calibration: la versión {self.version} no dice qué cambió. "
                "Poné 'changed' con el cambio respecto de la calibración anterior."
            )
        return self

    def as_line(self) -> str:
        cuando = f" ({self.fecha})" if self.fecha else ""
        return f"v{self.version}{cuando}" + (f" · {self.changed}" if self.changed else "")


class StrategyConfig(BaseModel):
    """El archivo de estrategia completo."""

    model_config = ConfigDict(extra="forbid")

    name: str
    universe: list[str] = Field(min_length=1)
    interval: Literal["1d"] = "1d"
    warmup_bars: int = Field(200, ge=0)
    direction: Literal["long"] = "long"
    indicators: dict[str, IndicatorSpec] = Field(default_factory=dict)
    entry: dict[str, Any]
    exits: ExitsConfig = Field(default_factory=ExitsConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    calibration: Calibration = Field(default_factory=Calibration)

    #: ruta del archivo del que salió (no se serializa al manifiesto)
    source_path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _reject_future_blocks(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            _reject_future(
                data,
                {
                    "entry_filters": "filtros de entrada por liquidez/earnings (Fase 3)",
                    "exit": "el bloque 'exit' suelto se reemplazó por 'exits.signal'",
                },
                "estrategia",
            )
        return data

    @field_validator("universe")
    @classmethod
    def _upper_unique(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for symbol in value:
            sym = str(symbol).strip().upper()
            if sym in out:
                raise ValueError(f"universe: el símbolo {sym} está repetido")
            out.append(sym)
        return out

    @model_validator(mode="after")
    def _check_rules(self) -> "StrategyConfig":
        names = self.available_names()
        _validate_node(self.entry, names, "entry")
        if self.exits.signal is not None:
            _validate_node(self.exits.signal, names, "exits.signal")
        return self

    @property
    def sizing_threshold_pct(self) -> float:
        """Distancia al stop, en % del precio, debajo de la cual manda el tope.

        El sizing por riesgo pide ``equity·risk_pct / distancia_al_stop`` acciones
        y el tope de concentración permite ``equity·max_position_pct / precio``.
        Igualando las dos:

            el tope ata  <=>  distancia_al_stop / precio  <  risk_pct / max_position_pct

        Con ``risk_pct: 1.0`` y ``max_position_pct: 20`` el umbral es 5%: cualquier
        stop más cercano que eso hace que ``risk_pct`` no decida nada.
        """
        return self.risk.position_sizing.risk_pct / self.risk.max_position_pct * 100.0

    def static_warnings(self) -> list[str]:
        """Avisos que se pueden dar sin mirar los datos. No son errores.

        Hay configuraciones donde que el tope mande es intencional (un universo
        muy volátil, un stop deliberadamente ancho), así que esto avisa y sigue.
        Con stops en ATR la distancia no se conoce hasta tener los datos: ese
        aviso lo da el motor al arrancar el backtest.
        """
        avisos: list[str] = []
        stop = self.exits.hard_stop
        if stop.mode == "pct" and stop.pct is not None and stop.pct < self.sizing_threshold_pct:
            avisos.append(
                f"risk_pct queda decorativo: el stop está a {stop.pct:.2f}% del precio y el "
                f"tope de concentración manda por debajo de "
                f"risk_pct/max_position_pct = {self.sizing_threshold_pct:.2f}%. "
                f"El tamaño lo va a decidir max_position_pct ({self.risk.max_position_pct}%), "
                f"no risk_pct ({self.risk.position_sizing.risk_pct}%)."
            )
        return avisos

    def available_names(self) -> set[str]:
        """Nombres que una condición puede usar como operando."""
        names: set[str] = set(OHLCV_COLUMNS)
        for alias, spec in self.indicators.items():
            outputs = indicator_outputs(spec.type)
            if outputs:
                names.update(f"{alias}.{col}" for col in outputs)
                if primary_output(spec.type):
                    names.add(alias)
            else:
                names.add(alias)
        return names


def _validate_node(node: Any, names: set[str], where: str) -> None:
    """Recorre el árbol all/any/not y valida cada hoja."""
    if not isinstance(node, Mapping):
        raise ValueError(f"{where}: se esperaba un mapeo, llegó {type(node).__name__}")

    combinators = [key for key in ("all", "any", "not") if key in node]
    if combinators:
        if len(combinators) > 1 or len(node) > 1:
            raise ValueError(f"{where}: 'all', 'any' y 'not' no se combinan en el mismo nivel")
        key = combinators[0]
        children = node[key]
        if key == "not":
            _validate_node(children, names, f"{where}.not")
            return
        if not isinstance(children, list) or not children:
            raise ValueError(f"{where}.{key}: se espera una lista con al menos una condición")
        for i, child in enumerate(children):
            _validate_node(child, names, f"{where}.{key}[{i}]")
        return

    # hoja: una condición atómica
    if "op" not in node or "left" not in node:
        raise ValueError(f"{where}: una condición necesita 'left' y 'op' (llegó {dict(node)})")
    if node["op"] not in OPERATORS:
        raise ValueError(
            f"{where}: operador '{node['op']}' desconocido. "
            f"Disponibles: {', '.join(OPERATORS)}"
        )
    for side in ("left", "right"):
        if side not in node:
            continue
        value = node[side]
        if isinstance(value, str) and value not in names:
            raise ValueError(
                f"{where}.{side}: '{value}' no es un indicador declarado ni una columna "
                f"OHLCV. Disponibles: {', '.join(sorted(names))}"
            )


class Settings(BaseModel):
    """``config/settings.yaml`` (no va al repo)."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["yahoo", "stooq", "local"] = "yahoo"
    cache_dir: Path = Path("data_cache")
    data_dir: Path = Path("tests/fixtures")
    reports_dir: Path = Path("reports")


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"no existe el archivo de configuración: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML inválido -> {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: se esperaba un mapeo en la raíz del YAML")
    return data


def load_strategy(path: str | Path) -> StrategyConfig:
    """Carga y valida un archivo de estrategia."""
    path = Path(path)
    data = load_yaml(path)
    try:
        config = StrategyConfig(**data)
    except ValidationError as exc:
        raise ConfigError(f"{path}:\n{_format_errors(exc)}") from None
    object.__setattr__(config, "source_path", path)
    return config


def load_settings(path: str | Path | None) -> Settings:
    if path is None:
        return Settings()
    try:
        return Settings(**load_yaml(path))
    except ValidationError as exc:
        raise ConfigError(f"{path}:\n{_format_errors(exc)}") from None


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        location = ".".join(str(p) for p in err["loc"]) or "(raíz)"
        lines.append(f"  - {location}: {err['msg']}")
    return "\n".join(lines)
