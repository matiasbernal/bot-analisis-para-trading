# Bot de análisis de trading — swing diario sobre acciones/ETFs

## Contexto

Matías quiere una herramienta que analice momentos de entrada y salida sobre acciones y
ETFs, con parámetros que él fija, y que además le permita validar esos parámetros contra
datos históricos antes de arriesgar dinero. No ejecuta órdenes: analiza, avisa y mide.

El repo `curso-php` hoy tiene 2 archivos sueltos de práctica (`index.php`, `index1.php`) y
se usa solo como almacenamiento. El bot es un proyecto nuevo e independiente que vive en
`trading-bot/` dentro del repo.

Decisiones ya tomadas con el usuario:

| Dimensión | Decisión |
|---|---|
| Mercado | Acciones y ETFs (US) |
| Timeframe | Swing, velas diarias |
| Alcance | Análisis + alertas + backtesting. **Sin ejecución de órdenes.** |
| Lenguaje | Python |
| Estrategia | Motor de reglas configurable por YAML, no una estrategia hardcodeada |
| Salidas | Siete capas configurables, incluida detección de reversión para salir antes del objetivo |
| Riesgo | Por trade (1R) **y** a nivel cartera: heat total, concentración, cortacircuito por drawdown |
| Disciplina | Journal de señales vs. ejecución real; el bot mide cuánto te desviás del plan |
| Rigor | Backtest riguroso (sin lookahead, con costos, con out-of-sample) |
| Interfaz | Config YAML + CLI, web UI, y alertas por Telegram. **Todo lo visual se diseña para el celular primero**; el escritorio es la versión ampliada, no al revés |

### Por qué Python y no PHP ni C#

- **PHP**: descartado para el motor. No tiene stack numérico (ni dataframes ni vectorización),
  no hay librerías de indicadores ni de backtesting, y los procesos largos son incómodos.
  Escribir el motor en PHP sería escribir a mano lo que en Python ya está resuelto y probado.
- **C#**: es una opción legítima y en algunos escenarios superior — tipado fuerte, buena
  performance, y existe `Skender.Stock.Indicators` (excelente) y el motor LEAN de QuantConnect.
  Es la elección correcta **si el objetivo final es ejecución real de baja latencia o una app
  de escritorio**. Para lo que se necesita acá — exploración de datos, iterar parámetros,
  graficar, recalcular backtests — la ceremonia de C# cuesta más de lo que aporta.
- **Python**: gana por ecosistema para esta tarea concreta: `pandas`/`numpy` para el cálculo
  vectorizado, `yfinance` para datos gratis, `plotly` para gráficos, notebooks para explorar.
- **Camino de migración**: si más adelante se quiere ejecución real, C# + LEAN es la migración
  natural. El diseño de abajo separa reglas (YAML) de motor, así que las estrategias sobreviven
  al cambio de lenguaje.

### Sobre optimización de parámetros (respuesta a la pregunta abierta)

Sí vale la pena, **pero no por la razón que parece**. Un grid search solo —probar 500
combinaciones y quedarse con la mejor— no hace el sistema más eficaz: lo hace *parecer* mejor
sobre datos pasados. Es la forma más rápida de sobreoptimizar.

Lo que sí sirve es el barrido **acompañado de walk-forward**: optimizar sobre una ventana,
validar sobre la siguiente sin tocar nada, y repetir. Eso no responde "cuáles son los mejores
parámetros" sino "¿esta estrategia aguanta fuera de muestra, o encontré ruido?". Esa segunda
pregunta es la única que importa. Va en Fase 6, después de que el backtest base sea confiable
— optimizar sobre un motor con bugs solo optimiza los bugs.

---

## Arquitectura

Cinco capas, cada una reemplazable sin tocar las otras:

```
datos  →  indicadores  →  reglas  →  backtest / scan  →  salida
```

```
trading-bot/
  pyproject.toml
  README.md
  .gitignore
  scripts/
    fetch_fixture.py               # se corre UNA vez en tu máquina: baja SPY/AAPL a tests/fixtures/
  config/
    settings.example.yaml          # provider, telegram token, paths (settings.yaml va en .gitignore)
    universe.yaml                  # lista de símbolos a vigilar
    strategies/
      ema_cross.yaml               # plantillas listas
      rsi_pullback.yaml
      breakout_52w.yaml
  tradingbot/
    config.py                      # carga YAML + valida con pydantic (errores claros, no KeyError)
    data/
      provider.py                  # ABC: get_ohlcv(symbol, start, end, interval) -> DataFrame
      yahoo.py                     # yfinance, auto_adjust=True
      stooq.py                     # fallback gratis para EOD diario
      cache.py                     # parquet local + descarga incremental
      validate.py                  # velas faltantes, duplicadas, volumen cero, NaN, gaps absurdos
    indicators/
      trend.py                     # sma, ema, macd, adx
      momentum.py                  # rsi, stochastic, roc
      volatility.py                # atr, bollinger, stdev
      volume.py                    # obv, volume_sma
      registry.py                  # "ema" -> función; es lo que hace que el YAML funcione
    strategy/
      conditions.py                # una condición atómica -> Series[bool]
      engine.py                    # compone all/any/not -> señales entry/exit
      risk.py                      # position sizing, cálculo de 1R
      position.py                  # estado de una posición abierta: R actual, pico, stop vigente
      exits.py                     # las 7 capas de salida y su orden de prioridad
      portfolio_risk.py            # heat total, concentración, límite por grupo, cortacircuito
    backtest/
      engine.py                    # loop barra a barra
      portfolio.py                 # cash, posiciones, equity curve
      costs.py                     # comisión + slippage
      metrics.py                   # CAGR, MDD, Sharpe, profit factor, expectancy...
      validation.py                # split in-sample / out-of-sample
      montecarlo.py                # remuestreo de la secuencia de trades → distribución de DD (Fase 6)
      optimize.py                  # grid search + walk-forward (Fase 6)
      manifest.py                  # cada corrida guarda YAML + hash de datos + commit → reproducible
    reporting/
      report.py                    # resumen + tabla de trades (consola y HTML responsive)
      charts.py                    # equity curve, drawdown, precio con marcas — plotly responsive
      templates/
        base.html                  # layout mobile-first compartido por informes y web
        report.html
    notify/
      telegram.py
      console.py
    scan.py                        # modo vivo: evalúa las reglas sobre las últimas velas
    journal.py                     # señales emitidas vs. lo que hiciste; positions.json / SQLite
    cli.py                         # typer: backtest | scan | status | fill | optimize | report
  web/
    app.py                         # FastAPI; solo lectura en Fase 4, edición en Fase 5
    auth.py                        # contraseña única + cookie; obligatorio si se expone en un VPS
    templates/                     # Jinja2 + HTMX, hereda reporting/templates/base.html
      hoy.html                     # señales del día
      posiciones.html              # R actual, stop vigente, días, earnings próximos
      backtest.html                # Fase 5: formulario + resultados
    static/
      app.css                      # mobile-first: una columna, breakpoints hacia arriba
      manifest.json                # PWA: "agregar a inicio" → abre como app, sin barra del navegador
  tests/
    fixtures/
      synthetic.py                 # OHLCV determinístico (seed fijo) — no necesita red
      candles.py                   # velas a mano para cada caso de salida
      SPY.csv, AAPL.csv            # reales, ~3 años; los genera scripts/fetch_fixture.py
    test_indicators.py
    test_no_lookahead.py           # el test más importante del proyecto
    test_conditions.py
    test_backtest_costs.py
    test_exits_intrabar.py         # gap bajo el stop, stop+objetivo misma vela, trailing nunca baja
    test_portfolio_risk.py
```

Dependencias (verificadas en PyPI el 2026-09-11, versiones fijadas en `pyproject.toml`):

```toml
requires-python = ">=3.11"
dependencies = [
  "pandas>=2.2,<3",        # 3.0 cambió Copy-on-Write y dtypes; ta/backtesting no están probados ahí
  "numpy>=1.26,<3",
  "yfinance>=1.7",
  "pyarrow>=15",           # parquet
  "pydantic>=2.7,<3",
  "pyyaml>=6",
  "typer>=0.12",
  "plotly>=5.22",
  "jinja2>=3.1",
  "requests>=2.31",
]
[project.optional-dependencies]
dev = ["pytest>=8", "ta>=0.11", "backtesting>=0.6"]   # ta: referencia para validar indicadores
web = ["fastapi>=0.110", "uvicorn>=0.29", "python-multipart>=0.0.9", "itsdangerous>=2.1"]  # Fases 4-5: formularios y cookie de sesión
```

`pandas-ta` **no está en PyPI** (se retiró); la referencia para validar indicadores es `ta`.

### Decisión: motor de backtest propio

Se escribe el motor en vez de usar `backtesting.py` o `vectorbt`. Razón: control total sobre
el modelo de ejecución y de costos, que es exactamente donde estas librerías esconden supuestos.
El riesgo es introducir bugs sutiles, y se mitiga así: una vez terminada la Fase 2, se corre
**la misma estrategia simple en `backtesting.py` y en nuestro motor y se comparan los números**.
Si divergen mucho, hay un bug nuestro. Es una verificación de una tarde y vale oro.

Dos decisiones de implementación que son baratas ahora y carísimas después:

- **Los indicadores se calculan vectorizados (pandas) una sola vez; el loop barra a barra
  corre sobre arrays `numpy`, nunca sobre `DataFrame.iterrows()`** (100× más lento). Con 4
  símbolos y 15 años no importa; con 200 símbolos y un grid de 300 combinaciones es la
  diferencia entre minutos y horas. Fase 6 paraleliza por símbolo/combinación con
  `multiprocessing`.
- **El motor es consciente de la dirección desde el día 1** (`direction: long` en el YAML,
  y `position.py` calcula R, stops y excursiones con signo). Short queda fuera de alcance,
  pero agregarlo después debe ser un flag, no una reescritura.

---

## El corazón: el archivo de estrategia

Todo lo que el usuario quiere tocar vive acá. Ningún parámetro queda hardcodeado en el código.

```yaml
# config/strategies/ema_cross.yaml
name: ema_cross_trend_filter
universe: [AAPL, MSFT, SPY, QQQ]
interval: 1d
warmup_bars: 200              # barras descartadas hasta que los indicadores son válidos

indicators:
  ema_fast:  {type: ema,  source: close, period: 20}
  ema_slow:  {type: ema,  source: close, period: 50}
  sma_trend: {type: sma,  source: close, period: 200}
  rsi:       {type: rsi,  source: close, period: 14}
  atr:       {type: atr,  period: 14}

entry:
  all:                                                    # AND
    - {left: ema_fast, op: crosses_above, right: ema_slow}
    - {left: close,    op: ">",           right: sma_trend}
    - {left: rsi,      op: "<",           right: 70}

entry_filters:                                          # condiciones que BLOQUEAN una entrada
  no_earnings_within_days: 5                              # no entrar si reporta en < 5 días
  min_avg_dollar_volume: 20_000_000                       # liquidez mínima (20 sesiones)
  min_price: 10

risk:
  position_sizing:   {mode: risk_pct, risk_pct: 1.0, on: current_equity}
  max_position_pct:  20          # ninguna posición supera el 20% del equity (tope de concentración)
  max_open_positions: 5
  max_portfolio_heat_r: 4.0      # suma del riesgo abierto (en R) no supera 4R → 4% del equity
  max_per_group: {sector: 2}     # no más de 2 posiciones del mismo sector (etiqueta en universe.yaml)
  circuit_breaker:
    monthly_drawdown_pct: 6      # si el mes va -6%, no se abren posiciones hasta el mes siguiente
    peak_drawdown_pct: 15        # si el equity cae 15% desde el máximo: se cierra todo y se frena

exits:                         # ver sección "Gestión de la posición abierta"
  signal:                      # la salida por reglas es UNA capa más, no un bloque aparte
    any:
      - {left: ema_fast, op: crosses_below, right: ema_slow}
  hard_stop:     {mode: atr, multiple: 2.0}
  trailing_stop: {mode: chandelier, multiple: 3.0, activate_after_r: 1.0}
  # Las demás capas quedan apagadas en las plantillas. Se prenden de a una, midiendo.

execution:
  signal_on:      close          # la regla se evalúa con la vela CERRADA
  fill_on:        next_open      # la orden se ejecuta en la apertura siguiente
  commission_pct: 0.05
  slippage_pct:   0.05

backtest:
  start:         2010-01-01
  end:           2025-12-31
  initial_cash:  10000
  in_sample_end: 2020-12-31      # todo lo posterior queda reservado como out-of-sample
```

**Operadores soportados** (`strategy/conditions.py`): `>`, `<`, `>=`, `<=`, `==`,
`crosses_above`, `crosses_below`, `between`, `rising`, `falling`, `pct_change_gt`.
Los lados `left`/`right` pueden ser un indicador declarado, una columna OHLCV, o una constante.
Esto permite componer estrategias muy distintas sin escribir Python.

**Sizing, en detalle** (`strategy/risk.py`), porque es donde más bugs silenciosos aparecen:
`acciones = floor(equity × risk_pct / (entrada − stop))`, luego se aplica el tope
`max_position_pct` (un stop muy ajustado sin tope produce posiciones gigantes) y se verifica que
haya cash. Acciones enteras, sin fraccionarias. Si el resultado es 0 acciones, no hay trade y
se registra el motivo.

### Riesgo a nivel cartera

Un trader con 20 años no piensa en "este trade": piensa en cuánto tiene expuesto en total y
cuándo debe dejar de operar. El plan original solo tenía riesgo por trade. Faltaba esto, y es
lo que evita que cinco operaciones correlacionadas se conviertan en una sola apuesta grande
(`strategy/portfolio_risk.py`):

| Control | Qué evita |
|---|---|
| `max_portfolio_heat_r` | Tener 5 posiciones de 1R cada una es tener 5% del equity en juego a la vez. Con 4R de tope, la quinta señal se descarta y queda registrada como "rechazada por heat". |
| `max_per_group` | Cinco tecnológicas no son cinco posiciones, son una. `universe.yaml` etiqueta cada símbolo (`sector`, `tema`) y el límite se aplica por grupo. |
| `max_position_pct` | Concentración. Independiente del riesgo: un trade de 0.5R que ocupa el 60% del capital sigue siendo una mala idea. |
| `circuit_breaker.monthly_drawdown_pct` | La racha mala. Cuando el mes va -6% se deja de abrir; las abiertas siguen con sus salidas. Es la regla que un trader disciplinado se impone a sí mismo, y el bot la hace mecánica. |
| `circuit_breaker.peak_drawdown_pct` | La invalidación del sistema. -15% desde el máximo no es una racha, es una señal de que el método o el mercado cambiaron. Se cierra todo y se para hasta revisar. |

El backtest respeta estos límites igual que el `scan`, así que los resultados históricos
reflejan las señales que **realmente** habrías podido tomar, no todas las que aparecieron.

> **Corrección de la tanda 1 — cómo se calcula el heat.** Al cerrar la tanda 1 se midió
> que el riesgo realizado de cada trade no es 1R: va de 0.54R a 0.99R (media 0.78R), porque
> el tamaño se redondea a acciones enteras y el tope de concentración recorta posiciones.
> Por eso `max_portfolio_heat_r` **no se evalúa contando R nominales** sino en pesos:
>
> ```
> heat = Σ(riesgo real de las posiciones abiertas) / equity      riesgo real = acciones × (entrada − stop)
> ```
>
> con `max_portfolio_heat_r: 4.0` leído como "4% del equity en riesgo abierto". Contar
> "cuatro posiciones de 1R" daría 4R nominales que en la práctica son ~3.1R, y el
> cortacircuito quedaría calibrado sobre una unidad que no es la que dice. Lo mismo vale
> para el riesgo que muestra la alerta de Telegram y para cualquier lectura en R de las
> rachas. Detalle y números en `README.md`, sección "La unidad de riesgo (1R)".

---

## Gestión de la posición abierta

Entrar es la parte fácil. Lo difícil —y donde se gana o se pierde la plata— es qué hacer una
vez adentro cuando el precio se da vuelta. Un stop fijo y un objetivo fijo dejan solo dos
salidas posibles; acá hay **siete capas de salida**, todas configurables y todas apagables.

Viven en `strategy/position.py` (estado de cada posición abierta) y `strategy/exits.py`
(evaluación de cada regla). Van en el bloque `exits:` del YAML de estrategia.

**Advertencia antes de la lista.** Siete capas suman ~25 parámetros. Un sistema con 25
parámetros de salida se puede ajustar para que cualquier histórico dé lindo, y eso no es una
estrategia, es una curva dibujada a mano. La regla es: **las plantillas arrancan con dos capas
prendidas (hard stop + trailing). Cada capa adicional se prende sola, se mide con la atribución
de salidas, y se queda solo si mejora la expectancy fuera de muestra.** Si dos capas hacen lo
mismo (giveback y trailing chandelier se pisan bastante), se elige una.

### 0. Salida por señal — la regla inversa de la entrada

```yaml
  signal:
    any:
      - {left: ema_fast, op: crosses_below, right: ema_slow}
```

Es el bloque `exit:` clásico, absorbido como una capa más para que el motor tenga **un solo
lugar** donde se decide salir, con un solo orden de prioridad y una sola atribución.

### 1. Hard stop — el piso que no se negocia

```yaml
  hard_stop:
    mode: atr                    # atr | pct | structure
    multiple: 2.0                # 2 × ATR(14) por debajo de la entrada
    # structure: usa el mínimo de swing previo en vez de una distancia calculada
```

Define el riesgo del trade (`1R`) y de ahí sale el tamaño de la posición. Es una orden que
vive en el mercado: se evalúa **intrabar** contra el `low` de cada vela. **Si la vela abre con
gap por debajo del stop, el fill es en la apertura, no en el precio del stop** — modelar esto
importa, es la diferencia entre un backtest honesto y uno que asume que siempre te sacan al
precio que querías.

### 2. Break-even — sacar el riesgo de la mesa

```yaml
  break_even:
    enabled: true
    trigger_r: 1.0               # cuando el trade va +1R...
    offset_pct: 0.1              # ...mové el stop apenas arriba de la entrada (cubre comisiones)
```

### 3. Trailing stop — seguir al precio hacia arriba

```yaml
  trailing_stop:
    enabled: true
    mode: chandelier             # chandelier | pct | structure | psar
    multiple: 3.0                # 3 × ATR desde el MÁXIMO alcanzado desde la entrada
    activate_after_r: 1.0        # no se activa hasta que el trade avanzó 1R
```

`chandelier` (ATR desde el máximo) es el más robusto para swing: se adapta a la volatilidad
del papel en vez de usar un % arbitrario. `structure` sigue los mínimos crecientes.

### 4. Deterioro de la tesis — *lo que pediste*

Acá está la respuesta a "el precio se dio vuelta por algún factor". No espera al stop: detecta
que las razones por las que entraste dejaron de existir.

El problema de disparar con una sola señal es que te saca de trades buenos en cualquier vela
roja. Por eso el modo por defecto es **acumulación de evidencia**:

```yaml
  reversal:
    mode: count                  # count | score | any
    min_count: 2                 # salir cuando 2 señales distintas coinciden
    lookback_bars: 3             # dentro de una ventana de 3 velas
    signals:
      - {name: close_below_ema,              params: {period: 20}}
      - {name: lower_low_break,              params: {lookback: 5}}
      - {name: bearish_engulfing_high_volume, params: {volume_mult: 1.5}}
      - {name: macd_hist_flip}
      - {name: rsi_cross_below,              params: {level: 50}}
      - {name: adx_falling,                  params: {period: 14, bars: 3}}
      - {name: volume_climax,                params: {mult: 2.0}}
```

Una vela roja aislada no hace nada. Cierre bajo la EMA20 **más** ruptura del mínimo de 5
barras saca la posición. `mode: any` existe para quien quiera salida al primer disparo.
Cada señal es una función en `strategy/exits.py` con su test.

**Por qué `count` y no `score` con pesos.** Existe `mode: score` con `weight` por señal, pero
no es el default: siete pesos más un umbral son ocho grados de libertad que se ajustan solos
al histórico. Contar señales coincidentes tiene un solo parámetro (`min_count`) y es casi
igual de expresivo. **Los pesos nunca entran en el grid search de la Fase 6** — se tocan a
mano, con razones, o no se tocan.

Estas condiciones se evalúan **al cierre** de la vela y ejecutan en la **apertura siguiente**
— a diferencia del hard stop, que es intrabar. Son dos modelos de ejecución distintos y el
motor los trata distinto.

### 5. Protección de ganancia y costo de oportunidad

```yaml
  giveback:
    enabled: true
    activate_after_r: 1.5        # solo una vez que hay ganancia real que proteger
    max_pct_of_peak: 40          # si devolvés 40% de la ganancia máxima no realizada, salís

  time_stop:
    enabled: true
    max_bars: 20                 # tras 20 velas...
    min_progress_r: 0.5          # ...si no llegó ni a +0.5R, el capital se libera
```

### 6. Riesgo externo — el "factor" que no está en el gráfico del papel

```yaml
  market_regime:
    enabled: true
    rule: {left: SPY_close, op: "<", right: SPY_sma_200}
    action: no_new_entries       # no_new_entries | reduce_50 | exit_all

  event_risk:
    exit_before_earnings_days: 2 # cerrar 2 días antes del reporte (el gap es una moneda al aire)
    gap_down_pct: 5              # si abre -5% o peor, salir en la apertura
```

El default del régimen es `no_new_entries`, no `exit_all`: cerrar todo cada vez que SPY cruza
su SMA200 produce latigazos brutales en mercados laterales (2015-2016, 2023). Dejar de abrir
y que las posiciones existentes salgan por sus propias reglas es lo que hace la mayoría de los
sistemas de swing que sobreviven. `exit_all` queda para quien lo quiera probar y medir.

Earnings tiene dos caras: no entrar cerca del reporte (`entry_filters.no_earnings_within_days`)
y salir antes si ya estás adentro. Para ETFs no aplica y el motor lo ignora. El filtro de
régimen requiere descargar SPY siempre, aunque no esté en el universo. Las fechas de earnings
salen de `yfinance` (`Ticker.earnings_dates`) y se cachean.

### Objetivo, con salidas parciales

```yaml
  take_profit:
    mode: rr
    ratio: 3.0
    partial:
      - {at_r: 1.5, pct: 50}     # vende la mitad en 1.5R y mueve el stop a break-even
      - {at_r: 3.0, pct: 50}     # el resto sigue con trailing
```

### Orden de prioridad dentro de una misma vela

Con velas diarias no se sabe qué pasó primero dentro del día. El motor resuelve con el criterio
**conservador** (siempre el peor caso para el trade), en este orden:

1. Gap de apertura por debajo del stop → fill en la apertura
2. Hard stop / break-even / trailing (contra el `low`)
3. Take profit (contra el `high`) — si en la misma vela se tocan stop y objetivo, **gana el stop**
4. Salidas evaluadas al cierre: signal, reversal, time stop, regime, earnings → fill en la
   apertura siguiente. Si varias disparan, la atribución registra **todas** las que dispararon,
   no solo la primera — si no, la estadística de "qué regla te saca" queda sesgada.

### La medición que vuelve todo esto útil

Cada regla de salida corta pérdidas **y también corta ganadores**. Sin medirlo es imposible
saber si sumó o restó. Por eso el informe incluye dos análisis específicos:

- **Atribución de salidas**: qué porcentaje de los trades salió por cada regla, y el P&L medio
  de cada grupo. Si el 60% sale por `reversal` con resultado medio negativo, la regla está
  sacándote temprano de trades que funcionaban.
- **Contrafáctico**: para cada salida anticipada, qué habría pasado sosteniendo hasta el
  objetivo o el hard stop. Responde directo "¿me conviene esta salida temprana?".
- **MAE / MFE** (máxima excursión adversa y favorable): cuánto llegó a ir en contra cada trade
  antes de terminar ganando, y cuánto a favor cada uno antes de terminar perdiendo. **Es la
  herramienta para calibrar el stop con datos y no a ojo**: si los ganadores casi nunca fueron
  más de 1.2 ATR en contra, un stop de 2 ATR está regalando riesgo.

---

## Las reglas de rigor (no negociables)

Esto es lo que separa un backtest útil de uno que miente:

1. **Sin lookahead.** El indicador en la barra `t` usa solo datos hasta `t`. La señal se evalúa
   al cierre de `t` y se ejecuta en la apertura de `t+1`. Hay un test dedicado que lo verifica
   alimentando el motor barra por barra y comparando contra el cálculo completo.
2. **Precios ajustados** por splits y dividendos (`auto_adjust=True`), o los cruces de medias
   son pura ficción.
3. **Costos siempre.** Comisión y slippage aplicados en cada entrada y cada salida.
4. **Stop conservador.** Si en una misma vela se tocan stop y take profit, gana el stop. No se
   puede saber cuál ocurrió primero con datos diarios.
5. **Benchmark obligatorio.** Todo informe compara contra *buy & hold* del mismo símbolo y
   contra SPY. Una estrategia que rinde menos que comprar y esperar no sirve, por linda que sea
   la curva.
6. **Out-of-sample reservado.** Se afinan parámetros solo sobre el período in-sample. El tramo
   final se toca una vez, al final. Si se mira 20 veces, deja de ser out-of-sample.

**Métricas del informe**: CAGR, Max Drawdown y su duración, Sharpe, Sortino, Calmar, Profit
Factor, Win Rate, Expectancy, ratio ganancia/pérdida media, cantidad de trades, % de tiempo
expuesto al mercado — más las mismas métricas del benchmark al lado. Se suman la atribución de
salidas, el contrafáctico y el análisis MAE/MFE descritos en la sección anterior.

Y tres cosas que un informe honesto muestra aunque duelan:

- **Cantidad de trades como semáforo.** Con menos de 30 trades el informe imprime en grande
  que **no se puede concluir nada**; con menos de 100, que las conclusiones son débiles. Un
  60% de aciertos sobre 12 operaciones es ruido.
- **Concentración del resultado.** Cuánto del P&L total viene de los 5 mejores trades. Si es
  el 80%, la estrategia no funciona: tuviste suerte dos veces. Una estrategia sana reparte.
- **Racha máxima de pérdidas consecutivas.** No para el backtest, para vos: si el histórico
  muestra 9 pérdidas seguidas, en vivo vas a vivir 9 pérdidas seguidas y tenés que saberlo
  antes para no abandonar el sistema justo cuando iba a recuperar.

7. **Reproducibilidad.** Cada corrida guarda un manifiesto (`backtest/manifest.py`): el YAML
   exacto, el hash del cache de datos, el commit del código y la fecha. Un resultado que no se
   puede reproducir seis meses después no es un resultado.

---

## Datos

**Primario: `yfinance`.** Gratis, sin API key, ~20 años de velas diarias de acciones y ETFs.
Es lo único que da suficiente historia gratis para un backtest serio.

**El riesgo y cómo se mitiga**: `yfinance` no usa una API oficial, scrapea endpoints de Yahoo
que cambian sin aviso (el rediseño de Yahoo de 2025 rompió scripts durante semanas). Por eso:

- `data/provider.py` define una interfaz abstracta; `yahoo.py` es una implementación entre otras.
- `data/cache.py` guarda todo en parquet local y solo descarga lo que falta. Si Yahoo se cae,
  los backtests siguen corriendo sobre el cache.
- `stooq.py` queda como fallback gratuito de EOD diario, sin API key.
- Si algún día se necesita confiabilidad de producción, se agrega un `alphavantage.py` o
  `twelvedata.py` implementando la misma interfaz. Ningún otro archivo cambia.

**Cuidado con Stooq como fallback**: ajusta por splits pero no por dividendos, así que sus
series no son comparables con las de Yahoo. Sirve para que el `scan` no se caiga un día que
Yahoo falla; no para mezclar proveedores dentro de un mismo backtest. El cache guarda de qué
proveedor vino cada serie y el motor se niega a mezclar.

**Validación antes de usar** (`data/validate.py`): velas faltantes en días hábiles, fechas
duplicadas, volumen cero, `high < low`, saltos de precio > 50% sin split registrado. Cualquiera
de esos frena el backtest con un mensaje claro. Un backtest sobre datos rotos da resultados
perfectos y falsos.

### Sesgo de supervivencia — el que no se puede arreglar del todo

Hacer backtest sobre `[AAPL, MSFT, NVDA]` es hacer trampa sin darse cuenta: los elegiste
sabiendo que ganaron. Cualquier estrategia de tendencia se ve genial sobre las acciones que
más subieron de la historia. Las que quebraron o fueron deslistadas no están en Yahoo.

Con datos gratuitos no hay solución completa. Lo que sí se hace:

- **Las plantillas se validan primero sobre ETFs amplios** (SPY, QQQ, IWM, sectoriales). Un
  ETF no quiebra ni se deslista; el sesgo casi desaparece.
- **El universo de acciones se define por reglas, no a dedo** (`universe.yaml` puede decir
  "los 50 de mayor volumen del S&P 500 al inicio de cada año"), y se documenta en el informe.
- **El informe lo dice explícitamente**: "universo elegido con información posterior; resultados
  optimistas". Que quede escrito, para que dentro de un año no lo olvides.

---

## Entorno de ejecución — lo que puede frenar, verificado

Chequeado en este entorno el 2026-09-11:

| Recurso | Estado | Consecuencia |
|---|---|---|
| Python 3.11.15, pip 24 | OK | `requires-python = ">=3.11"` |
| PyPI | OK (`pypi.org` está en la lista sin proxy) | se puede instalar todo |
| `query1.finance.yahoo.com` | **bloqueado** (403 en CONNECT, política de red del entorno) | acá no se puede descargar datos |
| `stooq.com` | **bloqueado** | ídem |
| `api.telegram.org` | **bloqueado** | acá no se puede mandar alertas |

**Consecuencia de diseño: todo lo que se construye acá se prueba sobre fixtures, no sobre
datos descargados.** No es una limitación grave — es como debería ser de todos modos: un test
que necesita internet no es un test. Pero cambia dónde se valida cada cosa:

- **Acá (sandbox)**: código, tests unitarios, backtest sobre fixtures, cotejo con
  `backtesting.py`, informes HTML.
- **En tu máquina**: primera descarga real, `scan` en vivo, Telegram, cron. Son los pasos 2,
  5 y "sobre datos reales" de la sección Verificación.
- **Alternativa**: la política de red del entorno se configura en la definición del entorno
  (<https://code.claude.com/docs/en/claude-code-on-the-web>). Es una lista de hosts a los que
  **este sandbox** puede salir; no afecta tu máquina ni tus cuentas. Si se permiten
  `query1.finance.yahoo.com`, `query2.finance.yahoo.com` y `stooq.com`, la descarga real se
  valida acá. **`api.telegram.org` conviene no habilitarlo acá**: es el único de los cuatro
  que escribe hacia afuera, y para usarlo el token del bot tendría que vivir en el entorno.
  Telegram se prueba en tu máquina o en el VPS. Riesgo de habilitar los dos hosts de datos:
  bajo — son endpoints públicos, de solo lectura, sin credenciales.

**Decisión tomada**: se amplía la política de red del entorno para los hosts de datos (no
Telegram). Receta exacta, según la documentación oficial de entornos cloud
(<https://code.claude.com/docs/en/cloud-environments#allow-specific-domains>):

1. En <https://claude.ai/code>, en la fila arriba del cuadro de mensaje, tocar el **ícono de
   nube** que muestra el nombre del entorno actual (por defecto, "Default"). No hay página de
   configuración ni URL directa: solo se llega desde ahí.
2. Pasar el mouse sobre el entorno y tocar el **ícono de engranaje** que aparece a la derecha.
3. En **Network access**, elegir **Custom**.
4. En **Allowed domains**, una línea por host:
   ```
   *.finance.yahoo.com
   finance.yahoo.com
   fc.yahoo.com
   stooq.com
   ```
   (`fc.yahoo.com` es donde `yfinance` obtiene la cookie de sesión antes de pedir datos; sin
   ese host la descarga falla aunque `query1` esté permitido.)
5. **Marcar "Also include default list of common package managers"**. Sin eso PyPI deja de
   ser alcanzable y `pip install` se rompe.
6. Guardar.

Dos cosas que la documentación deja claras: **las sesiones ya corriendo no releen la
configuración** — el cambio aplica a sesiones nuevas —, y cambiar los hosts permitidos vuelve
a ejecutar el setup script y regenera el cache del entorno en la próxima sesión. Por eso el
código se construye igual sobre fixtures: los tests que necesitan red detectan conectividad al
arrancar y se saltan con motivo si no la hay; en la primera sesión nueva con la política
ampliada se prenden solos.

**Dónde corre, decisión tomada**: en la PC con Windows durante las Fases 0–3; VPS cuando haya
señales reales que seguir (Fase 4). El código nace agnóstico del SO.

### Dónde corre el bot

Para swing diario el bot trabaja **un minuto por día**. "24/7 operativo" no aplica: no hay
nada que vigilar entre cierre y apertura. Lo que importa es otra cosa: **que corra todos los
días hábiles sin que te acuerdes**, y que el journal tenga una sola copia canónica.

| Etapa | Dónde | Por qué |
|---|---|---|
| Fases 0–3 (construir y validar el método) | Tu PC con Windows, a mano o con Task Scheduler | No hay señales que seguir todavía; un día sin correr no cuesta nada. Cero gasto. |
| Fase 4 en adelante (seguir señales de verdad) | VPS Linux chico (~USD 4–6/mes: Hetzner, DigitalOcean) con cron | Una PC apagada o dormida a las 18:30 ET se pierde el scan. El VPS no. Y la web UI (Fase 5) queda accesible desde el celular. |

Vale la pena el VPS, pero **recién cuando haya algo que perder**. Antes es gasto sin retorno.

Dos decisiones de diseño que salen de esto:

- **El código es agnóstico del SO desde el inicio**: `pathlib`, nada de rutas con barras
  fijas, nada de `cron`-isms en el código. El README trae las dos recetas: Task Scheduler en
  Windows y `crontab` en Linux.
- **Un scan tardío sigue sirviendo.** Las señales ejecutan en la apertura siguiente, así que
  el scan es válido en cualquier momento entre el cierre (18:30 ET) y la apertura del día
  siguiente (09:30 ET). Si el VPS falló a la noche, lo corrés a la mañana desde la PC y no
  perdiste nada. Por eso el journal es idempotente y vive en un archivo que se puede copiar.

Migrar de la PC al VPS es: `git clone`, `pip install`, copiar `settings.yaml` y `journal.db`,
agregar la línea de cron. Nada más.

**Fixtures** (`tests/fixtures/`):

- `synthetic.py`: generador determinístico de OHLCV (random walk con tendencia y volatilidad
  configurables, `seed` fijo). Sirve para el motor, los costos, el sizing y el riesgo de
  cartera. Un backtest sobre datos sintéticos con drift positivo **tiene** que dar resultados
  coherentes con ese drift; es un test de cordura barato.
- `candles.py`: velas escritas a mano para cada caso de salida (gap bajo el stop, stop y
  objetivo en la misma vela, trailing que intenta bajar, reversión por conteo).
- `SPY.csv`, `AAPL.csv` (~3 años, ~750 filas c/u): datos reales, generados **una vez en tu
  máquina** con `python scripts/fetch_fixture.py SPY AAPL` y commiteados. Hasta que existan,
  los tests que los usan se marcan `skip` con el motivo. No bloquean nada.

**Archivos que no van al repo** (`.gitignore`): `data_cache/`, `config/settings.yaml`,
`journal.db`, `reports/`, `.venv/`, `__pycache__/`.

### Contratos entre capas

Lo que hace que cinco módulos escritos por separado encajen sin discutir:

**OHLCV** — un `DataFrame` con índice `DatetimeIndex` tz-naive, nombre `date`, ordenado,
sin duplicados, una fila por día hábil; columnas `open high low close volume` (float64 salvo
`volume` int64); ajustado por splits y dividendos; sin NaN. `data/validate.py` lo garantiza
y es el único lugar donde se normaliza lo que devuelve cada proveedor.

**Indicador** — `def ema(df, period: int, source: str = "close") -> pd.Series`, alineada a
`df.index`, NaN durante el warmup. Los de varias salidas (MACD, Bollinger) devuelven un
`DataFrame` y el YAML los referencia como `macd.hist`, `bb.upper`. El registry es un
`dict[str, Callable]` y `config.py` valida que todo `type:` exista **antes** de descargar nada.

**Condición** — `evaluate(cond, ctx: dict[str, pd.Series]) -> pd.Series[bool]`.
`crosses_above` = `(l > r) & (l.shift(1) <= r.shift(1))`; la primera barra siempre es `False`.

**Trade** (dataclass, lo que va a la tabla y al journal) — `symbol, entry_date, entry_price,
shares, risk_per_share, stop_initial, exit_date, exit_price, exit_reasons: list[str], pnl,
pnl_r, bars_held, mae_r, mfe_r, commission, slippage`.

**Posición abierta** — `symbol, entry_date, entry_price, shares, risk_per_share, stop_current,
peak_price, bars_held, partial_taken`. Es lo que `journal.py` persiste y lo que `scan` lee.

**Orden del loop por barra `t`** (`backtest/engine.py`), fijo y documentado en el código:

1. Apertura de `t`: llenar las órdenes pendientes de `t-1` a `open[t]` ± slippage; para las
   posiciones abiertas, si `open[t] < stop` → salida por gap a `open[t]`.
2. Intrabar `t`: `low[t] <= stop` → salida al stop; si no, `high[t] >= objetivo` → salida.
3. Cierre de `t`: actualizar pico, trailing, break-even; evaluar entradas y salidas por cierre
   → órdenes pendientes para `t+1`. Si hay más entradas que lugares, se ordenan por símbolo
   (determinístico; `entry_ranking` configurable después).
4. Registrar equity a `close[t]` (mark-to-market).

**Métricas, sin ambigüedad** (`backtest/metrics.py`): retornos diarios de la curva de equity;
Sharpe = media/desvío × √252, tasa libre de riesgo 0; Sortino igual con desvío de los
negativos; CAGR = (E_fin/E_ini)^(365.25/días) − 1; MDD sobre el máximo acumulado; Calmar =
CAGR/|MDD|; Profit Factor = suma ganancias / suma pérdidas; Expectancy = media de `pnl_r`.

### Lo que sé de `yfinance` 1.7 que va a morder si no se contempla

- `Ticker(sym).history(start, end, auto_adjust=True)` devuelve columnas planas; `yf.download`
  devuelve `MultiIndex` y es más frágil. Se usa `history`.
- El índice viene tz-aware (`America/New_York`) → `tz_localize(None)`. Columnas capitalizadas
  → minúsculas. Trae `Dividends` y `Stock Splits` → se descartan.
- Devuelve un `DataFrame` **vacío sin error** si el símbolo no existe o si te limitó la tasa.
  Vacío = error, siempre.
- Rate limit: descarga secuencial con pausa de ~0.5 s entre símbolos; nunca `threads=True`.
- **Los precios ajustados cambian retroactivamente** cada dividendo o split. Un cache que solo
  agrega barras nuevas al final queda inconsistente. Regla en `cache.py`: al refrescar, se
  bajan las últimas 30 barras y se comparan con el cache; si difieren más de 1e-6 relativo, se
  rebaja el histórico completo. Un sidecar JSON guarda `provider`, `fetched_at`, `adjusted`.
- `Ticker.earnings_dates` cubre ~3 años hacia atrás más los próximos. **En un backtest de 15
  años, las reglas de earnings solo aplican donde hay fechas**, y el informe dice en qué % de
  trades había información. En el `scan` (vivo) aplican siempre. Para ETFs, no aplican.
- Los sectores para `max_per_group` se escriben a mano en `universe.yaml`. Hay un
  `cli universe-enrich` que consulta `Ticker.info["sector"]` una vez y los completa — es lento
  y limitado por tasa, se corre una vez y se commitea el resultado.

**`scan` es idempotente**: la clave del journal es `(symbol, bar_date, kind)`. Correrlo dos
veces el mismo día no duplica alertas; correrlo un feriado no emite nada nuevo.

---

## Fases

**Fase 0 — Base.** Scaffolding, `pyproject.toml`, `.gitignore`, capa de datos con cache y
validación, `config.py` con pydantic, fixtures sintéticos. Verificable acá: `pytest` sobre
cache (escribe, lee, detecta inconsistencia en el solape) y sobre `validate.py` (rechaza cada
tipo de dato roto). Verificable en tu máquina: descargar 15 años de AAPL, cortar internet,
volver a correr y que salga del cache.

**Fase 1 — Indicadores.** SMA, EMA, RSI, MACD, ATR, Bollinger, ADX + registry.
Verificable: tests contra `ta` sobre el fixture sintético (tolerancia 1e-8) y contra valores
publicados a mano para RSI y ATR (que tienen variantes de suavizado — se fija Wilder).

**Fase 2 — Motor y backtest.** Condiciones, composición all/any, portfolio, costos, métricas,
CLI `backtest`. Arranca con hard stop y take profit solamente. Es la fase más grande.
Verificable: `test_no_lookahead.py` en verde y la comparación contra `backtesting.py` sobre un
cruce de medias simple.

**Fase 3 — Gestión de la posición abierta.** Las seis capas de salida, el orden de prioridad
intrabar, y las métricas de atribución / contrafáctico / MAE-MFE. Se construye sobre un motor
ya validado, no antes. Verificable: correr la misma estrategia con cada capa prendida y apagada
y comparar — si una capa no mejora la expectancy, queda apagada por defecto.

**Fase 4 — Informes, scan, journal y web de solo lectura.** Informe HTML con equity curve,
drawdown y gráfico de precio con marcas de entrada/salida y el motivo de cada salida. Comando
`scan` que corre las reglas sobre las últimas velas. Alertas por Telegram + cron diario
post-cierre. Y una **web mínima de solo lectura** (`/hoy`, `/posiciones`, `/informes`) que
muestra en el celular lo mismo que `cli status` — se adelanta desde la Fase 5 porque es el
momento en que aparecen las primeras señales reales y querés verlas desde el teléfono, no
desde una terminal.

Las alertas traen **números, no adjetivos**. Una señal que dice "entrada en MSFT" no sirve
para operar; esta sí:

```
🟢 ENTRADA · MSFT
Mañana en apertura (orden MOO)

Comprar: 24 acciones (~$10.100)
Riesgo:  1.0R = $101
Stop:    $404.30 (2.0 ATR)
Target:  $445.60 (3R)

Motivo: EMA20 cruzó EMA50
        precio > SMA200 · RSI 58

Cartera: 3/5 · heat 2.9R/4R
Régimen: alcista

🔴 SALIDA · AAPL
Mañana en apertura

Motivo: reversión 2/2
        cerró bajo EMA20
        rompió mínimo 5 días
Estado: +1.4R · máx +2.1R · 11 días
```

El formato está pensado para la pantalla de un teléfono: **una idea por línea, ninguna línea
de más de ~36 caracteres**, sin tablas que se rompan al envolver. Los números clave (acciones,
stop, target) van primero porque es lo único que necesitás para cargar la orden. Cada alerta
lleva al final un link a la web (`/hoy`), para ver el gráfico si hace falta.

El `scan` mantiene estado de las posiciones abiertas (`journal.py`, SQLite) para poder evaluar
trailing, break-even, giveback y time stop. Sin memoria de a qué precio entraste y cuál fue el
máximo alcanzado, la mitad de las capas de salida no se pueden calcular.

**El journal es la herramienta de disciplina.** Registra cada señal emitida y, con `cli fill`,
lo que vos hiciste de verdad: el precio al que entraste, si entraste, si saliste antes o
después. De ahí salen dos informes que ningún backtest da:

- **Tracking error**: tu equity real contra la equity teórica del sistema. Si divergen, o hay
  slippage que el modelo no captura, o te estás desviando del plan. Las dos cosas hay que
  saberlas.
- **Costo de las desviaciones**: cada vez que no seguiste una señal (o seguiste una que no
  existía), qué habría pasado. Al cabo de seis meses tenés un número: "desviarme del plan me
  costó X". Es el argumento más convincente que existe para apegarse al sistema — o, si el
  número es positivo, la prueba de que tu criterio le suma y hay que codificarlo.

`cli status` imprime la foto de la semana: posiciones abiertas con su R actual y su stop
vigente, earnings próximos, estado del régimen, heat de cartera, y si el cortacircuito está
activo. Es lo que un trader disciplinado mira el domingo a la noche.

**Operación diaria, en concreto.** La vela diaria de Yahoo queda definitiva recién después del
cierre (16:00 ET) y tarda en asentarse; el cron corre a las **18:30 ET** (19:30 en Argentina).
Las señales se ejecutan en la apertura siguiente con órdenes *market-on-open* — exactamente lo
que el backtest asume con `fill_on: next_open`. Si operás distinto de eso (a media rueda, con
límite), el backtest ya no describe lo que hacés.

**Fase 5 — Web completa.** Sobre la web de la Fase 4: formulario para editar parámetros de
entrada y de salida, botón de correr backtest (en segundo plano, con progreso), tabla de trades
y gráficos, `fill` desde el celular (confirmar a qué precio entraste, sin abrir una terminal).
Sobre el mismo motor, sin duplicar lógica.

### Mobile-first: reglas concretas para todo lo visual

No es "que se vea bien en el celular"; es **diseñar para el celular y dejar que crezca**. Vale
para el informe HTML, la web y las alertas:

- **CSS de una columna por defecto**, breakpoints solo hacia arriba (`min-width`). Nada de
  `max-width` para "arreglar" el móvil después. Base: Pico CSS classless (la misma que usás
  en `index.php`) — responsive sin escribir casi nada, y sin build step.
- **Sin framework de JS.** Jinja2 en el servidor + HTMX para lo interactivo (refrescar
  posiciones, lanzar un backtest). Carga en menos de un segundo con 4G; no hay bundle.
- **Métricas como tarjetas apiladas**, no como tabla. Una tabla de 12 columnas en un teléfono
  es ilegible; doce tarjetas con número grande y etiqueta chica, no.
- **Tablas de trades con scroll horizontal propio** (`overflow-x: auto` en su contenedor),
  columnas esenciales primero (símbolo, R, motivo de salida), el resto a la derecha. La página
  nunca hace scroll horizontal.
- **Gráficos Plotly con `responsive: true`**, altura relativa al ancho (no fija en píxeles),
  leyenda abajo en pantallas angostas, barra de herramientas oculta, zoom táctil habilitado.
  El gráfico de velas con marcas de entrada/salida es el que más se mira desde el teléfono:
  arranca mostrando las últimas 60 barras, no los 15 años.
- **Toques, no clics**: objetivos táctiles de mínimo 44 px, nada que dependa de `hover`.
- **PWA mínima**: `manifest.json` + meta tags → "agregar a pantalla de inicio" y abre como
  app, a pantalla completa. Sin service worker en v1 (el contenido cambia una vez por día;
  no vale la complejidad del cache offline).
- **Modo oscuro** siguiendo `prefers-color-scheme`. A las 19:30 con el teléfono en la mano,
  una página blanca molesta.
- **Auth obligatoria antes de exponer en un VPS**: contraseña única en `settings.yaml`, cookie
  de sesión, HTTPS con Caddy adelante (certificado automático). Sin eso, cualquiera con la URL
  ve tus posiciones y puede lanzar backtests que consumen tu CPU.

**Verificación específica**, y esta sí se puede hacer acá: Chromium y Playwright ya están
instalados en el entorno. Cada página se captura a **390 px** (iPhone), **412 px** (Android
común) y **1280 px**, y se revisa: sin scroll horizontal, texto legible sin zoom, gráficos que
se adaptan, botones alcanzables con el pulgar. Las capturas van al informe de cierre de la fase
como evidencia.

**Fase 6 — Optimización walk-forward y Monte Carlo.** Grid search sobre rangos de parámetros
declarados en el YAML, con ventanas deslizantes de optimización/validación, y un informe que
muestra la degradación in-sample vs out-of-sample. Si la degradación es grande, la estrategia
era ruido. Solo entran al grid los parámetros de entrada, hard stop y trailing; los pesos de
reversión y los umbrales de cartera no se optimizan.

Monte Carlo (`backtest/montecarlo.py`): remuestrear el orden de los trades históricos miles de
veces para obtener la **distribución** del drawdown máximo, no el único valor que dio el
histórico. El backtest dice "el peor drawdown fue 12%"; Monte Carlo dice "con estos mismos
trades en otro orden, el 5% de los escenarios pasa de 22%". Ese segundo número es el que decide
cuánto capital ponés y dónde va el cortacircuito.

Propuesta: implementar **Fases 0 a 2 completas en la primera tanda** — sin backtest confiable
el resto no tiene sobre qué pararse — y la Fase 3 inmediatamente después, en la segunda tanda.

---

## Definición de terminado — Tanda 1 (Fases 0, 1 y 2)

Se declara terminada cuando **todo** esto es cierto, con la salida pegada como evidencia:

- [ ] `pip install -e ".[dev]"` limpio en un venv nuevo con Python 3.11.
- [ ] `pytest -v` en verde, incluidos `test_no_lookahead.py`, `test_exits_intrabar.py` (solo
      hard stop y take profit en esta tanda) y `test_backtest_costs.py`.
- [ ] `tradingbot backtest --strategy config/strategies/ema_cross.yaml --data tests/fixtures/`
      imprime el informe completo sobre el fixture sintético, con benchmark al lado.
- [ ] Sobre el sintético con drift positivo, buy & hold da CAGR positivo y la estrategia da un
      número coherente (no NaN, no infinito, no 10.000%).
- [ ] Cotejo con `backtesting.py` sobre el cruce de medias: CAGR, trades y MDD dentro del 5%.
- [ ] Prueba de lookahead deliberado: el resultado es absurdamente bueno. El motor correcto no.
- [ ] Un mismo backtest corrido dos veces da métricas y manifiesto idénticos.
- [ ] `config.py` rechaza con mensaje claro: un `type:` inexistente, un operador desconocido,
      un `in_sample_end` posterior a `end`, `risk_pct` negativo.
- [ ] Un commit por fase en `claude/trading-analysis-bot-8ehd5h`, push al cerrar la tanda.
- [ ] `README.md` con: instalar, generar fixtures reales en tu máquina, correr un backtest,
      leer el informe.

Lo que **no** entra en la tanda 1, para que no se cuele: trailing, break-even, reversión,
giveback, time stop, régimen, earnings, riesgo de cartera, scan, Telegram, web, optimización.
Todo eso es tanda 2 en adelante, sobre un motor ya validado.

## Verificación

Al terminar cada tanda, evidencia concreta, no "listo". Marcado con **[máquina]** lo que
requiere red y se corre en tu computadora, no acá:

1. `pytest tests/ -v` — en particular `test_no_lookahead.py` y los tests de indicadores.
2. **[máquina]** `tradingbot backtest --strategy config/strategies/ema_cross.yaml --symbol SPY`
   → descarga real, informe en consola con métricas y comparación contra buy & hold.
3. Cotejo cruzado: misma estrategia simple en `backtesting.py`, comparar CAGR, cantidad de
   trades y max drawdown. Deben ser cercanos.
4. Prueba de cordura del sesgo: correr una estrategia *deliberadamente* con lookahead (mirando
   el cierre de mañana) y comprobar que da resultados absurdamente buenos. Si el motor correcto
   da lo mismo, hay un bug.
5. **[máquina]** `tradingbot scan --strategy ... --universe config/universe.yaml`
   → señales del día, contrastadas a mano contra el gráfico de 2 símbolos. Y una alerta de
   prueba a Telegram con `tradingbot notify-test`.
6. Salidas: test con velas sintéticas para cada capa (un gap por debajo del stop debe llenar en
   la apertura; stop y objetivo en la misma vela debe resolver por el stop; el trailing nunca
   puede bajar). Y sobre datos reales, un caso conocido revisado a mano en el gráfico — por
   ejemplo NVDA en el desplome de agosto 2024 — verificando que el bot marca la salida donde
   corresponde y no dos semanas tarde.
7. Riesgo de cartera: test con señales sintéticas simultáneas — la sexta señal con heat en 4R
   debe rechazarse y quedar registrada; tres señales del mismo sector con `max_per_group: 2`
   deben dejar una afuera; un mes a -6% debe bloquear entradas hasta el mes siguiente.
8. Reproducibilidad: correr dos veces el mismo backtest y verificar que el manifiesto y las
   métricas son idénticos byte a byte.
9. Responsive: capturas con Playwright del informe HTML y de cada página web a 390, 412 y
   1280 px; `document.documentElement.scrollWidth <= innerWidth` en todas (sin scroll
   horizontal); gráficos con ancho igual al contenedor; ningún botón menor a 44 px.

## Qué es esto, en la jerga

Es **trading sistemático (algorítmico) con ejecución manual**. La parte algorítmica está
completa: entradas, salidas y sizing son determinísticos, sin discrecionalidad — el mismo YAML
sobre los mismos datos da siempre las mismas señales. Lo único que no se automatiza es mandar
la orden al broker.

Esa omisión es deliberada y el orden importa: primero se valida que el método tiene expectancia
positiva, después se automatiza la ejecución. El bloque `execution:` ya separa *cuándo se genera
la señal* de *cuándo se ejecuta la orden*, así que agregar más adelante un `execution/broker.py`
(Alpaca, IBKR) es sumar un módulo, no rediseñar.

No tiene relación con HFT, market making ni arbitraje estadístico: comparten el nombre pero son
otra disciplina, con otra infraestructura.

## Fuera de alcance

Ejecución de órdenes reales, brokers, API keys con permiso de trading, apalancamiento, opciones,
short selling (el motor lo contempla, no se implementa), piramidación (agregar a ganadores),
e intradía (limitado por la historia gratuita).
