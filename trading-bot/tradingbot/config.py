"""Carga y validación de la configuración (YAML -> pydantic).

Todo lo que el usuario toca vive en el YAML de estrategia. Acá se valida
**antes de descargar un solo dato**: que cada ``type:`` exista en el registry de
indicadores, que cada operador exista, que cada operando se pueda resolver, y
que las fechas y los porcentajes tengan sentido. Un KeyError a los diez minutos
de backtest no es un mensaje de error.

Lo que todavía no está implementado (break-even, reversión, giveback, time
stop, régimen, earnings) se rechaza con un mensaje que dice explícitamente que
es del torneo de la tanda 2C, en vez de ignorarse en silencio y hacer creer que
el backtest lo tuvo en cuenta.
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


#: capas previstas en el plan que son del torneo de la tanda 2C y todavía no existen
_TANDA_2 = {
    "break_even": "break-even (Fase 3)",
    "reversal": "salida por reversión (Fase 3)",
    "giveback": "giveback (Fase 3)",
    "time_stop": "time stop (Fase 3)",
    "market_regime": "filtro de régimen de mercado (Fase 3)",
    "event_risk": "riesgo de eventos / earnings (Fase 3)",
}

def _reject_future(data: Mapping[str, Any], table: Mapping[str, str], where: str) -> None:
    for key, label in table.items():
        if key in data:
            raise ValueError(
                f"{where}: '{key}' es {label}; TODAVÍA NO ESTÁ IMPLEMENTADO. "
                "Sacalo del YAML o esperá la tanda que lo trae: un backtest que "
                "ignora media configuración en silencio miente."
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


class CircuitBreaker(BaseModel):
    """Los dos cortes que paran el sistema, con horizontes distintos a propósito.

    ``monthly_drawdown_pct`` es la racha mala: se deja de abrir, las posiciones
    abiertas siguen con sus salidas, y el mes que viene se arranca de cero. Es la
    regla que un trader disciplinado se impone y el bot hace mecánica.

    ``peak_drawdown_pct`` es otra cosa: no es una racha, es la sospecha de que el
    método o el mercado cambiaron. Cierra todo y **no se reanuda solo** — el
    backtest no vuelve a abrir en lo que queda del período, porque reanudar
    automáticamente convertiría la invalidación del sistema en una pausa, que es
    justo lo que no es.
    """

    model_config = ConfigDict(extra="forbid")

    monthly_drawdown_pct: float | None = Field(None, gt=0, le=100)
    peak_drawdown_pct: float | None = Field(None, gt=0, le=100)

    @model_validator(mode="after")
    def _algo_que_hacer(self) -> "CircuitBreaker":
        if self.monthly_drawdown_pct is None and self.peak_drawdown_pct is None:
            raise ValueError(
                "circuit_breaker: hay que poner al menos uno de monthly_drawdown_pct "
                "o peak_drawdown_pct; un bloque vacío no hace nada y hace creer que sí"
            )
        return self


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_sizing: PositionSizing = Field(default_factory=PositionSizing)
    max_position_pct: float = Field(20.0, gt=0, le=100)
    max_open_positions: int = Field(5, ge=1)

    #: tope de riesgo abierto, leído como **% del equity** y no como R nominales:
    #: 4.0 es "4% del equity en riesgo abierto". El motivo está en README, "La
    #: unidad de riesgo": contar cuatro posiciones de 1R daría 4R nominales que en
    #: la práctica son ~3.1R, y el cortacircuito quedaría calibrado sobre una
    #: unidad que no es la que dice.
    max_portfolio_heat_r: float | None = Field(None, gt=0)
    #: ``{etiqueta: máximo}``, p.ej. ``{sector: 2}``. Las etiquetas salen de
    #: universe.yaml; si falta la etiqueta de algún símbolo, el motor falla en vez
    #: de aplicar un límite a medias.
    max_per_group: dict[str, int] | None = None
    circuit_breaker: CircuitBreaker | None = None

    @field_validator("max_per_group")
    @classmethod
    def _grupos_positivos(cls, value: dict[str, int] | None) -> dict[str, int] | None:
        for etiqueta, tope in (value or {}).items():
            if tope < 1:
                raise ValueError(
                    f"max_per_group.{etiqueta}: el tope es {tope}; con 0 no se podría "
                    "abrir ninguna posición y eso no es un límite, es apagar el sistema"
                )
        return value


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


class TrailingStop(BaseModel):
    """Chandelier: el stop sigue al máximo alcanzado, a ``multiple`` × ATR.

    Entra en la tanda 2A **por decisión de diseño del PLAN** ("las plantillas
    arrancan con dos capas prendidas: hard stop + trailing"), no porque se haya
    medido que aporta. Es la línea base contra la que el torneo de la 2C mide al
    resto, así que no compite en el torneo. El informe lo dice donde aparece.

    ``activate_after_r`` es de una sola vía: una vez que el trade llegó a ese
    umbral la capa queda armada aunque el precio vuelva. Si se desarmara al
    retroceder, el trailing se desengancharía justo durante el retroceso, que es
    cuando hace falta (ver la invariante 3 de ``position.py``).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    mode: Literal["chandelier"] = "chandelier"
    multiple: float = Field(3.0, gt=0)
    atr_period: int = Field(14, ge=1)
    #: no se activa hasta que el trade avanzó esta cantidad de R. 0 = desde la entrada.
    activate_after_r: float = Field(1.0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _reject_future_modes(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            mode = data.get("mode")
            if mode in {"pct", "structure", "psar"}:
                raise ValueError(
                    f"trailing_stop mode '{mode}' está previsto en el plan pero no "
                    "implementado: la tanda 2A hace solo 'chandelier'"
                )
        return data


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
    trailing_stop: TrailingStop | None = None
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


class UniverseEntry(BaseModel):
    """Una fila de ``config/universe.yaml``: el símbolo y sus etiquetas."""

    model_config = ConfigDict(extra="allow")

    symbol: str

    @field_validator("symbol")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value).strip().upper()


def load_universe(path: str | Path) -> dict[str, dict[str, str]]:
    """``{símbolo: {etiqueta: valor}}`` a partir de ``config/universe.yaml``.

    Las etiquetas son libres (``sector``, ``tema``, y las que se agreguen): el
    límite por grupo se aplica sobre la que nombre el YAML de estrategia, así que
    acá no hay una lista cerrada. Lo que sí se normaliza es el símbolo, para que
    ``spy`` y ``SPY`` no sean dos cosas.
    """
    data = load_yaml(path)
    filas = data.get("symbols")
    if not isinstance(filas, list) or not filas:
        raise ConfigError(f"{path}: se esperaba una lista en 'symbols'")

    universo: dict[str, dict[str, str]] = {}
    for fila in filas:
        if not isinstance(fila, Mapping):
            raise ConfigError(f"{path}: cada símbolo va como mapeo, llegó {fila!r}")
        try:
            entry = UniverseEntry(**fila)
        except ValidationError as exc:
            raise ConfigError(f"{path}:\n{_format_errors(exc)}") from None
        etiquetas = {k: str(v) for k, v in fila.items() if k != "symbol"}
        universo[entry.symbol] = etiquetas
    return universo


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
