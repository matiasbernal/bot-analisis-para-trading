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
  take_profit:   {mode: rr, ratio: 3.0}
  # Las demás capas —el trailing incluido— quedan apagadas en las plantillas. Se prenden
  # de a una, midiendo. (2026-09-13: el trailing dejó de ser línea base y pasó a ser
  # candidata del torneo. El motivo, medido, está en "El torneo de capas".)

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

> **Corrección de la tanda 1 — la alerta y las rachas.** El riesgo en pesos de cada
> señal SÍ se conoce la noche anterior (las acciones y el riesgo por acción se fijan al
> cierre), así que la alerta puede imprimirlo exacto; lo que no se conoce es el precio
> del stop, que se ancla al fill de la apertura y va como distancia, no como precio.
> Y cualquier lectura tipo "cinco pérdidas seguidas son −5R" está inflada en la misma
> proporción que la unidad: el informe publica el costo de la peor racha en plata.
> Formato completo en `README.md`, "Qué puede decir la alerta".

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
estrategia, es una curva dibujada a mano. La regla es: **las plantillas arrancan con la línea
base prendida (hard stop + take profit). Cada capa adicional —el trailing chandelier
incluido— se prende sola, se mide con la atribución de salidas, y se queda solo si gana el
torneo contra la línea base.** Si dos capas hacen lo mismo (giveback y trailing chandelier se
pisan bastante), se elige una; las dos compiten por ese lugar y ninguna lo tiene reservado.

> **Corrección (2026-09-13) — la línea base era de tres capas y ahora es de dos.** La versión
> original decía "arrancan con dos capas prendidas (hard stop + trailing)", con el objetivo
> dado por supuesto. Al medir el poder del torneo sobre esa línea base salió que prenderla
> deja **cero capas medibles** de las cuatro estimables, `break_even` incluida, que con el
> trailing prendido tiene un efecto disponible de 0.16R contra un MDE de 0.43R: no se
> distingue del ruido ni capturando el 100% de su mejor caso. El trailing pasó a ser
> candidata del torneo. El fundamento completo, con los dos números que lo motivaron, está
> en "El trailing dejó de ser línea base", más abajo.

> **Corrección (2026-09-12).** La versión original de esta regla decía "si mejora la
> expectancy **fuera de muestra**". Aplicada capa por capa, esa regla se contradice con la
> regla de rigor 6: seis decisiones mirando el tramo 2021-2025 son seis miradas al
> out-of-sample, y a partir de la segunda deja de serlo. Cada capa se decide con
> walk-forward **dentro del in-sample**; el out-of-sample se gasta una vez, al final del
> torneo, sobre la configuración que quedó. El procedimiento completo está en "El torneo de
> capas", más abajo, y es la forma en que se loteó la Fase 3.

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

### El torneo de capas — cómo se decide qué queda prendido

*(Agregado el 2026-09-12, al lotear la Fase 3. Reemplaza la idea de que las capas son una
sola entrega.)*

La Fase 3 tal como estaba escrita pedía las seis capas juntas y al mismo tiempo pedía medir
cada una sola. Las dos cosas no caben en una entrega, por dos razones independientes.

**Primera: el presupuesto de out-of-sample.** Seis decisiones binarias tomadas mirando el
tramo 2021-2025 son seis miradas al out-of-sample. Con α = 0.05 por decisión, la
probabilidad de quedarse con **al menos una** capa que en realidad no aporta es
1 − 0.95⁶ ≈ **26%**, y ese 26% no se ve: la capa queda prendida en la plantilla y parece
validada. El propio informe imprime la regla que eso viola ("el out-of-sample se mira una
vez, al final").

**Segunda: el instrumento.** "Se queda solo si mejora la expectancy" supone que la mejora se
puede medir. La expectancy tiene error estándar σ_R/√n; con los 31 trades de la plantilla
actual eso es del orden de ±0.3R, y una capa que mejore 0.1R es invisible. Construir seis
capas para después descubrir que el instrumento no las resuelve es el orden equivocado: el
poder de medición se calcula **antes**, y si no alcanza, lo que cambia es el universo y el
período, no las capas.

#### El procedimiento

1. Cada capa se decide **dentro del in-sample** (`backtest.in_sample_end`). El in-sample se
   parte en tramos consecutivos y la capa tiene que mostrar el mismo signo en los tramos,
   no solo en el agregado: una mejora que vive entera en un tramo es un régimen de mercado,
   no una capa.
2. Si la capa solo se prende o apaga (parámetros fijos por la plantilla), con eso alcanza:
   es validación repetida, no ajuste. Si además se tocan sus parámetros, el tramo *k* se usa
   para elegirlos y el *k+1* para medirlos, sin volver atrás — walk-forward de verdad.
3. **El out-of-sample se gasta una sola vez**, al final del torneo, sobre la configuración
   ganadora completa. No hay una mirada por capa. Si el out-of-sample contradice al
   in-sample, se reporta y se vuelve a la línea base (hard stop + take profit); no se reabre
   el torneo sobre el mismo tramo, porque ahí ya dejaría de ser out-of-sample. Qué cuenta
   como "contradice" y qué no, en "El criterio, fijado antes de que existan los datos" §2.3:
   no alcanza con que el out-of-sample no dé significativo.
4. La cantidad de tramos está acotada por el poder: un tramo con cinco trades no decide
   nada. El número de tramos sale del cálculo de poder, no de partir el calendario en
   pedazos iguales.

#### Las dos reglas de desempate

- **El default es apagada.** Empate estadístico = la capa no entra. La carga de la prueba es
  de la capa, no del stop: cada capa que se prende agrega parámetros, y los parámetros se
  pagan en sobreajuste aunque el backtest no lo muestre.
- **Una mejora de expectancy que viene con menos trades no es una mejora** hasta mirar
  `return_on_risk` y el heat. Una capa que corta la mitad de los trades puede subir la
  expectancy por trade y bajar el retorno sobre el riesgo desplegado: la expectancy pondera
  cada trade igual, y si quedan menos trades y cada uno arriesga lo mismo, el capital rinde
  menos con mejor número por trade. Las dos métricas se miran juntas o no se mira ninguna.

#### El criterio, fijado antes de que existan los datos

*(Escrito el 2026-09-13, con los CSV reales todavía sin bajar. **Esa es la razón de que esté
escrito ahora y no después**, y es la misma por la que se reserva el out-of-sample: un
criterio definido con los datos a la vista se acomoda a lo que los datos dicen, y el que lo
acomoda no se da cuenta. Lo de abajo son reglas, no intenciones: cada una tiene que poder
ejecutarse leyendo una salida del banco sin volver a discutir nada.)*

Hasta acá el PLAN decía "se queda si mejora la expectancy" y eso no alcanza para ejecutar:
no dice con qué intervalo, ni qué pasa con un empate, ni qué hace una capa que no se puede
medir, ni cuántas veces se puede mirar el out-of-sample. Las cuatro cosas, en orden.

##### Los cinco estados en los que puede terminar una capa

El vocabulario primero, porque la mitad de las reglas son sobre la diferencia entre dos de
estos estados y esa diferencia se pierde si las dos se escriben "apagada":

| estado | qué pasó | ¿vuelve? |
|---|---|---|
| **GANADORA** | se midió y ganó según 2.1 | queda prendida en la configuración |
| **RECHAZADA** | se midió y no ganó (empate o peor) | solo en la pasada final, con el umbral de 2.4 |
| **NO EVALUADA** | no se midió: su exigencia superaba el corte de 2.2 | sí, sola, el día que haya *n* suficiente |
| **NO ESTIMABLE** | ni siquiera se pudo calcular la exigencia | cuando exista lo que falta (`reversal`: la capa escrita) |
| **PENDIENTE** | bloqueada por el entorno (`event_risk`: red) | como pasada de reevaluación, cuando haya red |

**La diferencia entre RECHAZADA y NO EVALUADA es la que más importa y la más fácil de
perder.** Una capa rechazada se midió y perdió: la evidencia existe y apunta en contra. Una
capa no evaluada no tiene evidencia de ninguna clase; lo que falló fue el instrumento, no la
capa. Escribir las dos como "apagada por defecto" convierte una falta de datos en un
veredicto, que es exactamente lo que el módulo de poder existe para no hacer.

##### 2.1 Qué hace falta para declarar una capa GANADORA

Se mide con el banco A/B pareado por trade (`tradingbot comparar`), **dentro del in-sample**,
contra la configuración vigente en ese punto del orden. Las cuatro condiciones son
conjuntas: falta una y la capa es RECHAZADA.

1. **El intervalo, y no el punto.** El delta pareado de expectancy tiene que dar un intervalo
   de confianza del 95% por bootstrap **enteramente por encima de cero** — o sea, cota
   inferior > 0. Un punto estimado positivo con el cero adentro es un empate, y un empate no
   entra (primera regla de desempate). Esto es lo que faltaba: `+0.18R` no dice nada sin su
   intervalo, y `+0.18R [−0.61, +0.95]` dice que no se sabe.
2. **El mismo signo en todos los tramos.** El punto estimado tiene que tener el mismo signo
   en cada tramo del walk-forward, no solo en el agregado. Una mejora que vive entera en un
   tramo es un régimen de mercado y no una capa. Esto no pide significancia por tramo —no la
   va a haber— pide consistencia de signo.
3. **Y el piso de cuenta.** Al menos `MIN_AFECTADOS` = 10 trades efectivamente tocados por la
   capa. Es el mismo piso de la regla del cociente inestable: una media de menos de diez
   números le pasa su varianza al resultado. Con menos de diez, la capa es NO EVALUADA y no
   RECHAZADA, porque lo que falló fue la muestra.
4. **El segundo par de ojos, cuando la capa cuesta trades.** Si la configuración candidata
   toma **menos trades** que la vigente —porque bloquea entradas, o porque salir antes cambia
   qué señales entran por cash y por heat—, la expectancy sola no alcanza: `return_on_risk`
   tiene que ser **mayor o igual** que el de la configuración vigente, y el heat máximo no
   puede subir. Si la expectancy mejora y `return_on_risk` empeora, es empate y la capa no
   entra. No hay umbral que calibrar acá a propósito: **cualquier** pérdida de trades activa
   el segundo par de ojos, porque un umbral sería un parámetro más que elegir mirando los
   datos. (Y hay una razón técnica: los trades que existen en un brazo y no en el otro no
   tienen par, así que el bootstrap pareado no los ve. La condición 4 es lo único que los
   mira.)

**Empate explícito.** Si el intervalo contiene el cero, el veredicto es RECHAZADA con el
intervalo publicado al lado, no "no concluyente". Con el poder ya publicado por capa antes de
la corrida, un empate en una capa medible **sí** es información: significa que el efecto, si
existe, es menor que su MDE.

##### 2.2 Qué hace falta para declarar una capa NO EVALUADA, y qué pasa entonces

Hoy el corte de ~1/3 vive implícito en los veredictos que imprime `poder.py`. Explícito:

> **Una capa cuya exigencia supera 1/3 no entra al torneo.** Queda apagada, registrada como
> **NO EVALUADA** con su exigencia, su *n* y la configuración contra la que se calculó.

La exigencia es `MDE por trade afectado / efecto disponible`: qué fracción del **mejor caso**
tiene que capturar la capa, en cada trade que toca, para distinguirse de un empate. El corte
en 1/3 es un juicio y se declara como tal: ninguna capa real captura su mejor caso —un
chandelier devuelve 3 ATR antes de sacarte, un break-even sale exactamente en cero cuando el
trade habría vuelto—, así que pedirle más de un tercio es pedirle un milagro y después leer
el empate como "no aporta". **El número queda fijado ahora, con los datos sin bajar.** Se
puede mover, pero solo con un argumento que no mencione el resultado de ninguna corrida; un
1/3 que se convierte en 1/2 después de ver que una capa quedó afuera no es una calibración,
es la conclusión eligiendo su premisa.

Cuatro consecuencias operativas:

- **La exigencia se recalcula en el turno de cada capa**, contra la configuración vigente en
  ese momento, no contra la línea base inicial. Es el mismo hecho que hizo caer al trailing:
  cada capa que entra baja el efecto disponible de las que siguen, así que una capa puede
  ser medible al empezar el torneo y no serlo cuando le toca. Eso no es un error del torneo,
  es lo que el torneo mide, y va registrado con el orden.
- **NO EVALUADA no es un final.** La capa vuelve sola cuando el universo crezca lo suficiente
  para que su exigencia caiga bajo el corte, y el propio informe publica cuánto falta:
  `poder.trades_necesarios` da los trades y `universo.py` los traduce a símbolo-años.
- **No se toca `α` ni la potencia para que una capa entre.** Bajar la potencia al 60% baja el
  MDE y "hace medible" a cualquier capa: lo que compra es más falsos negativos disfrazados de
  medición. α = 5% y potencia = 80% quedan fijos para todo el torneo.
- **Y el torneo puede quedarse sin capas.** Si ninguna pasa el corte, el resultado del torneo
  es la línea base, con las cinco fichas de NO EVALUADA al lado y el *n* que haría falta. Eso
  es un resultado y se publica como tal; no es motivo para bajar el corte.

##### 2.3 El out-of-sample: cuántas veces, qué es una contradicción y cuál gana

**Cuántas veces: una.** Una corrida, sobre la configuración ganadora completa, al final del
torneo. "Una" es literal y mecánico: si la corrida se rompe, o los datos estaban mal, o se
quiere repetir con un detalle cambiado, **eso es una segunda mirada** y se registra como tal
en el manifiesto. El contador de miradas al out-of-sample va en el manifiesto de la corrida,
no en la memoria de nadie.

**Antes de gastarlo se publica su poder.** El tramo out-of-sample tiene su propio *n* y por
lo tanto su propia exigencia. Si con ese *n* la configuración ganadora no se puede distinguir
de la línea base ni capturando todo su efecto disponible, **el out-of-sample no puede
contradecir nada** y hay que decirlo antes de mirarlo: gastarlo igual es gastarlo para
enterarse de que no alcanzaba. En ese caso la salida correcta es no correrlo y reportar la
configuración como validada solo in-sample.

**Qué es una contradicción**, definido sobre el mismo estadístico del torneo (delta pareado
de la configuración ganadora contra la línea base, ahora sobre el tramo reservado):

| resultado OOS | definición | qué se hace |
|---|---|---|
| **CONFIRMA** | mismo signo que el in-sample, y el intervalo del 95% contiene el punto estimado in-sample | la configuración queda |
| **DEGRADA** | mismo signo, pero el intervalo excluye el punto estimado in-sample | la configuración queda, y el informe publica la degradación con los dos números. No se re-ajusta nada |
| **NO CONCLUYE** | el intervalo contiene al cero y al punto in-sample | la configuración queda, marcada como validada solo in-sample. Es el resultado **esperable** con un tramo chico, no una sorpresa |
| **CONTRADICE** | **signo opuesto** al in-sample **y** el intervalo excluye el punto estimado in-sample | se vuelve a la línea base |

La definición estricta es deliberada: un out-of-sample que no alcanza significancia **no**
contradice nada, porque eso es lo que pasa cuando no hay poder, y tratarlo como contradicción
haría que el tramo reservado tumbe cualquier resultado por falta de datos.

**Cuál gana: el out-of-sample, y gana restando y no sustituyendo.** Una contradicción no
convierte a la configuración opuesta en ganadora: devuelve todo a la línea base (hard stop +
take profit) y deja el torneo sin resultado. La razón es la que hace que el tramo valga algo:
se lo miró **una** vez, así que puede decir "no", que es una decisión binaria sobre una
hipótesis fijada de antemano, pero no puede **elegir** entre configuraciones — elegir es
mirar varias veces con otro nombre. Después de una contradicción el torneo no se reabre sobre
el mismo tramo; lo que se puede hacer es conseguir más datos y correr un torneo nuevo con un
tramo out-of-sample nuevo, con el anterior marcado como gastado.

##### 2.4 La pasada final: con qué criterio entra una capa que ya perdió

La pasada final ya estaba escrita —las RECHAZADAS se vuelven a medir contra la configuración
ganadora— y le faltaba lo principal: **con qué umbral**. Si es el mismo de 2.1, el orden deja
de importar y el torneo se vuelve circular; además cada capa pasaría a tener dos oportunidades
con α = 5% cada una, que es la multiplicidad que este PLAN entero existe para no pagar.

> **En la pasada *k*, una capa entra solo si su intervalo por bootstrap al nivel
> `1 − α/k` queda enteramente por encima de cero.** Primera medición (el torneo): 95%.
> Segunda (la primera pasada final): 97.5%. Tercera: 98.3%. Y así.

Es la corrección de multiplicidad que corresponde a haberla medido *k* veces, y tiene una
propiedad que resuelve el otro problema: **se aprieta sola**, así que la pasada no puede
ciclar. Las tres reglas que la acompañan:

- **Tope duro de tres mediciones.** Una capa medida tres veces sin entrar queda RECHAZADA y
  cerrada para este torneo. Vuelve al siguiente, con más datos.
- **La pasada final solo suma, nunca saca.** Una capa que ya ganó no se re-mide para sacarla:
  eso sería re-decidirla contra una línea base posterior, o sea reabrir el torneo. Si al final
  dos capas se pisan —el caso `giveback` contra `trailing_stop`—, el informe **publica** la
  redundancia con su número y no la resuelve; se resuelve en el torneo siguiente. La única
  excepción es la capa que en la configuración final **dispara en cero trades**: eso no es una
  medición sino una observación, y se apaga por código muerto.
- **Las NO EVALUADAS no participan de la pasada final.** No perdieron nada que re-medir, y la
  configuración ganadora tiene *menos* efecto disponible que la línea base, así que su
  exigencia solo puede haber empeorado. Lo que las trae de vuelta son datos, no pasadas.

**Y todo esto se registra o no vale**: el orden usado, el estado final de cada capa, el
intervalo y el α de cada medición, la cantidad de veces que se midió cada una, y el contador
de miradas al out-of-sample. Un resultado de torneo sin eso no es reproducible, que es la
regla de rigor 7 aplicada a una decisión en vez de a una corrida.

#### El torneo depende del orden, y hay que decirlo

Las capas interactúan, así que el resultado **no es una propiedad de la capa sino del par
(capa, línea base contra la que se midió)**. Si `break_even` entra primero, `giveback` se
mide contra una línea base que ya lo tiene, y con el orden invertido el resultado puede ser
otro. El caso evidente es `giveback` contra `trailing` (se pisan), pero no es el único:
`time_stop` y `reversal` compiten por los mismos trades laterales, y `break_even` le saca
trabajo al `trailing`.

Dos consecuencias, las dos obligatorias:

- El orden del torneo se elige por costo de instrumento (de menos grados de libertad a más,
  para gastar el in-sample en las decisiones baratas primero) y **queda registrado junto al
  resultado**. Un resultado de torneo sin su orden no es reproducible.
- **Pasada final de reevaluación.** Cuando el torneo termina, las capas **RECHAZADAS** se
  vuelven a medir **contra la configuración ganadora**, no contra la línea base. Una capa
  puede no aportar sobre dos capas y sí sobre cinco: `break_even` descartado solo puede
  tener sentido una vez que `time_stop` cambió la distribución de trades que llegan vivos a
  +1R. Si alguna entra en esta pasada, la pasada se repite con la configuración nueva, hasta
  que ninguna entre. **Con qué umbral entra ahí, que no es el mismo del torneo**, y por qué
  las NO EVALUADAS no participan: §2.4 de "El criterio, fijado antes de que existan los
  datos".

#### El poder de medición es uno por capa, no uno global

Un MDE global miente. Una capa que toca todos los trades (`trailing`, `break_even`) tiene
mucho más poder que una que toca el 15% (`market_regime`, `event_risk`): si la capa cambia
el resultado de una fracción *f* de los trades, el efecto mínimo detectable **por trade
afectado** escala con 1/√(f·n), y el efecto sobre la expectancy global con √(f/n). Entre
f = 1.0 y f = 0.15 hay un factor 2.6: con el mismo universo y el mismo período, una capa
rara necesita un efecto 2.6 veces más grande para ser medible.

Por eso el informe publica **una fila por capa** con su fracción estimada de trades
afectados, el efecto mínimo detectable por trade afectado, el efecto equivalente en
expectancy global, y el margen que esa capa tiene disponible (cuánta R hay realmente en
juego, de MAE/MFE). Una capa cuyo MDE supera su margen disponible **no se mide**: se declara
no medible con este universo y este período, y eso se dice en vez de reportar un empate como
si fuera información.

Ese flag binario es **condición necesaria y nada más**, y el criterio que decide de verdad es
la exigencia con el corte en 1/3 de §2.2: el efecto disponible es el mejor caso de la capa, y
ninguna capa real lo captura entero. Una capa que pasa el flag con una exigencia del 70% no
es medible, es una capa a la que se le va a pedir un milagro y después se va a leer el empate
como "no aporta".

#### `event_risk` y la red

`event_risk` es la única capa que depende de un dato externo que el entorno puede no tener
(`Ticker.earnings_dates` necesita red). **Decisión: el torneo se declara completo sin ella.**
`event_risk` queda pendiente con su motivo escrito, y se mide cuando haya red, como una
pasada de reevaluación más contra la configuración ganadora. Una capa bloqueada por política
de entorno no frena a las otras seis: si lo hiciera, el proyecto quedaría esperando algo que
no depende del código.

---

## Cash real: antes de medir nada

*(2026-09-15, antes de la línea base sobre ETFs reales de más abajo. Se escribe
acá y no ahí porque contamina cualquier medición previa, no solo la que sigue.)*

Con los CSV reales bajados, `scripts/universo.py` mostró algo que ningún fixture
sintético había mostrado: de 77 señales rechazadas sobre los 13 ETFs con
`ema_cross_sin_trailing`, **44 eran "no hay cash para comprar ni 1 acción"**.
`initial_cash: 10000` contra ETFs de $50 a $600 dejaba muy poco margen: con
`risk_pct: 1.0` y `max_position_pct: 30`, una sola posición grande podía agotar
el cash disponible para el resto, y el motor rechazaba señales que ninguna regla
de riesgo quiso rechazar — la plata simplemente no alcanzaba. Cualquier medición
sobre esa línea base — ritmo de trades, riesgo realizado, quién decide el
tamaño — estaba parcialmente midiendo el tamaño de la billetera, no la
estrategia.

**La corrección: `initial_cash: 100000` en las cinco plantillas** (`ema_cross`,
`ema_cross_sin_trailing`, `cartera_correlacionada`, `rsi_pullback`,
`extra_bollinger_upper_break`), con `calibration.version` subida en cada una.
Nada del lado de las reglas cambió — ni entrada, ni salida, ni los topes en
porcentaje —, así que es un cambio de escala del capital y no de la estrategia.

### Lo que cambió al medir de nuevo

**El riesgo realizado se pega mucho más a 1.00R.** Sobre el universo sintético
de la tanda 1 (`ema_cross_sin_trailing`, 31 trades, tope 30%):

| | $10.000 | $100.000 |
|---|---|---|
| mínimo | 0.828R | 0.884R |
| media | 0.948R | 0.990R |
| máximo | 0.997R | 1.000R |
| desvío | 0.038 | 0.020 |

Con posiciones de cientos de acciones en vez de 3 a 13, el redondeo a acciones
enteras pesa una fracción mucho más chica del riesgo declarado. Sigue sin haber
ningún trade por encima de 1.00R: el motor arriesga menos de lo declarado, nunca
más, con cualquiera de los dos capitales.

**Un efecto secundario que vale la pena anotar, y no es un error**: con el tope
en 30% (el que "duerme" el sesgo por ATR, ver `ESTADO.md` sección 4), el
coeficiente de correlación entre el riesgo realizado y la distancia al stop subió
de 0.06 a 0.39 al subir el cash, aunque el sesgo medido en R casi no se movió
(0.002R → 0.014R). Es la regla del cociente inestable
(`tradingbot/backtest/cocientes.py`) actuando sobre una correlación: al bajar el
desvío de 0.038 a 0.020, el poco ruido que queda —dos trades atados por el tope
en vez de uno— se ve más grande en una estadística normalizada por ese desvío
más chico. El efecto en plata sigue siendo chico frente al sesgo despierto del
tope 20% (0.30R), que es lo que importa para decidir si el sesgo está dormido.
`tests/test_riesgo_realizado.py` fija las dos lecturas, no solo la correlación,
para no repetir el error que la regla del cociente inestable existe para evitar.

**Sobre los 13 ETFs reales, el cash sigue siendo la categoría que más rechaza,
pero con menos margen sobre el cupo.** `ema_cross_sin_trailing`, cupo 5:

| | $10.000 | $100.000 |
|---|---|---|
| trades tomados | 246 | 249 |
| rechazos totales | 77 | 74 |
| por cash | 44 | 43 (40 + 3 al fill) |
| por cupo (`max_open_positions`) | 31 | 31 |
| trades si el cupo fuera 99 | 250 | 260 |

El cash sigue ganándole al cupo (43 contra 31), así que la conclusión de fondo
—subir `max_open_positions` no destraba el n del torneo, el cash sí importa—
**no cambia**. Lo que sí cambió es el margen: con $10.000 sacar el cupo del medio
compraba apenas 4 trades más; con $100.000 compra 11. El cash dejó de ser tan
degenerado como para ahogar casi toda la señal que el cupo también bloquea, y
eso hace más visible que el cupo también pesa, no que el cupo pasó a ganar.

`tests/test_universo.py` fija el nuevo n (249, 1.30 t/símbolo-año) y la nueva
distancia entre cash y cupo. `tests/test_riesgo_realizado.py` fija la nueva
distribución del riesgo realizado y los conteos de quién decidió el tamaño con
el tope viejo (20%), que sigue existiendo como el régimen que ejercita el aviso.

### Qué NO cambió

El sizing degenerado por cash era un problema del **capital de la plantilla**,
no del motor ni de las reglas: `strategy/risk.py` ya sabía recortar por cash y
registrar el motivo (`"no hay cash para comprar ni 1 acción"`), y lo seguía
haciendo correctamente con $10.000. Lo que hacía falta no era código nuevo, era
darle a la plantilla el capital que un cruce de medias sobre ETFs necesita para
que el cash deje de ser el límite que decide casi la mitad de los rechazos.

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
   final se toca una vez, al final. Si se mira 20 veces, deja de ser out-of-sample. **Prender
   o apagar una capa de salida cuenta como una mirada**: seis capas decididas contra el
   out-of-sample lo gastan seis veces (ver "El torneo de capas").

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

**Fase 3 — Gestión de la posición abierta.** Las capas de salida, el orden de prioridad
intrabar, y las métricas de atribución / contrafáctico / MAE-MFE. Se construye sobre un motor
ya validado, no antes. Verificable: correr la misma estrategia con cada capa prendida y apagada
y comparar — si una capa no mejora la expectancy, queda apagada por defecto.

**No es una sola entrega** (loteo decidido el 2026-09-12; el fundamento está en "El torneo de
capas"). Va en tres, y el criterio del corte no es el tamaño sino qué hace falta para que una
capa sea medible:

| | Qué entra | Por qué acá |
|---|---|---|
| **2A** | Estado de la posición abierta (`position.py`), el banco de comparación A/B con bootstrap pareado por trade, el poder de medición publicado por capa, y `trailing_stop` chandelier | El estado es el piso de cuatro capas, no una capa. El banco y el poder son el instrumento: sin ellos "se queda si mejora" no se puede ejecutar. **El poder se publica antes de escribir la primera capa**: si no alcanza, lo que cambia es el plan de la tanda, y es más barato saberlo con una capa escrita que con seis |
| **2B** | Riesgo de cartera: heat total en pesos, `max_per_group`, cortacircuito por drawdown | Va **antes** del torneo, no después: el riesgo de cartera cambia el tamaño de las posiciones, y el tamaño cambia toda expectancy en pesos y todo drawdown. Si el torneo corre primero, las seis mediciones quedan obsoletas el día que entra el heat y hay que repetirlas |
| **2C** | El torneo: `break_even`, `time_stop`, `giveback`, `trailing_stop`, `reversal`, `market_regime`, de a una y en ese orden, más la pasada final de reevaluación | Orden por grados de libertad creciente, para gastar el in-sample en las decisiones baratas primero. Acá ese orden coincide con el de **consumo de efecto disponible**, así que la capa más agresiva queda al final y no antes. `trailing_stop` y `giveback` se pisan, y el orden decide cuál se mide contra cuál: `giveback` va primero por ser la más barata de las dos |

`trailing_stop` **se construye en 2A pero se decide en 2C**, como cualquier otra capa. Entra
en 2A porque el estado de la posición abierta y el banco A/B son su instrumento y porque el
torneo necesita una capa escrita para calibrarse; lo que **no** hace es entrar prendida. Las
plantillas arrancan sin ella. `event_risk` queda fuera de 2C por la red, con la decisión
escrita arriba.

#### El trailing dejó de ser línea base

*(Decidido el 2026-09-13, sobre el análisis de `ESTADO.md` §12. **Es consecuencia de una
medición, no de una preferencia**, y el número está abajo para que no se relea como otra
cosa.)*

**El número que lo motivó.** Con el trailing chandelier prendido como línea base, proyectado
a n=230 y con el corte de exigencia de ~1/3, **ninguna de las cuatro capas estimables del
torneo queda medible**. El caso extremo es `break_even`: su efecto disponible cae de **0.99R
a 0.16R** (independiente) y de 0.99R a 0.27R (correlacionado), contra un MDE de 0.43R, así
que deja de distinguirse del ruido incluso capturando el 100% de su mejor caso. `time_stop`,
que sin trailing era la mejor candidata del torneo con una exigencia del 23-27%, pasa a
necesitar el 66/43%. El mecanismo no es ruido y está medido: **σ baja** (1.43R → 1.18R), el
chandelier comprime la distribución y el MDE por trade afectado mejora. Lo que se derrumba es
el denominador. Medir se volvió más fácil y no alcanzó, porque quedó mucho menos para medir.

**Qué cambia, en una línea:** el trailing no se apaga y no se recalibra. **Cambia de
estatus.** Pasa de línea base a candidata del torneo, y la línea base pasa a ser **hard stop
+ take profit solamente**.

Las dos cosas que quedan explícitamente descartadas, para que no vuelvan por la ventana:

- **Apagarlo** no: el banco A/B da empate y el contrafáctico muestra que la capa acierta en
  el 59-71% de los trades que toca. No hay evidencia de que reste; hay evidencia de que no se
  sabe, que es distinto.
- **Recalibrarlo** tampoco: la grilla de `multiple` × `activate_after_r` identifica el
  mecanismo pero no puede elegir el reemplazo, porque los dos universos sintéticos se
  contradicen sobre el óptimo (2 ATR/0.5R es la mejor celda en el independiente y la peor en
  el correlacionado). Elegir ahí sería elegir el generador. Si algún día se toca el
  multiplicador, tiene que ser por un argumento estructural y no por esa tabla.

**El argumento que decide, y es de asimetría y no de evidencia.** Una capa que compite puede
terminar prendida —si gana, queda—, mientras que una capa que es línea base **no puede
terminar apagada jamás**, porque nunca se la mide. Mientras ser línea base era gratis eso no
importaba; ahora está medido y cuesta el torneo entero. **El default caro es el que no se
puede revisar.**

##### En qué posición del orden entra — las dos opciones, y cuál

Si el trailing compite, hay que decir dónde. Es la capa que más efecto disponible consume, así
que la posición no es un detalle de presentación: **decide cuántas de las otras quedan
medibles.**

**Opción A — primera, por ser la más agresiva.** El argumento a favor es que así se mide
contra la línea base más limpia que va a existir, con todo su efecto disponible intacto, que
es la condición en la que su exigencia es más baja (18% a n=315). El argumento en contra es
decisivo: es justamente la capa con más efecto disponible (1.68R) y más fracción tocada
(f = 0.53), o sea la que más probablemente gane, y si gana primero **el resto del torneo
vuelve a medirse contra una línea base con trailing** — que es exactamente el estado que esta
decisión vino a corregir, reintroducido por otro camino. Se habría cambiado el estatus de la
capa sin cambiar ninguna de sus consecuencias.

**Opción B — en el orden de grados de libertad, o sea después de `break_even`, `time_stop` y
`giveback`.** El argumento en contra es que la deja medirse contra una línea base que ya se
comió parte de lo que ella tenía para capturar, así que puede salir no medible. El argumento
a favor es que **esa es la asimetría correcta**: la capa con más grados de libertad (modo
categórico de cuatro valores, multiplicador, activación y período de ATR) y más agresión es
la que tiene que probarse contra una casa llena, no la que elige primero.

**Recomendado: opción B.** Tres razones, en orden de peso:

1. **Los dos criterios coinciden, así que no hay que inventar uno nuevo.** El PLAN ya ordena
   el torneo por grados de libertad crecientes. Medido sobre los fixtures, el consumo de
   efecto disponible de cada capa (`f × efecto disponible`, que es la R por trade de cartera
   que la capa se lleva si se prende) ordena casi igual, y deja al trailing último en los dos
   universos y con las dos líneas base:

   | capa | consumo, indep. (4) | consumo, corr. (10) |
   |---|---|---|
   | `market_regime` | 0.20R | 0.15R |
   | `break_even` | 0.23R | 0.19R |
   | `giveback` | 0.28R | 0.40R |
   | `time_stop` | 0.82R | 0.67R |
   | **`trailing_stop`** | **0.90R** | **0.90R** |

   Poner el trailing primero pediría un criterio propio para él solo, y el único disponible
   —"es el default de hoy"— es el que acaba de quedar descartado.
2. **Es la única de las tres tablas del proyecto en la que los dos universos sintéticos no se
   contradicen.** La grilla de parámetros da órdenes opuestos según el fixture y por eso no
   decide nada; el ranking de consumo da el mismo orden en los dos, y el trailing queda
   último en los dos por un margen grande (0.90R contra 0.67-0.82R del segundo). Un orden que
   sobrevive al cambio de generador es un orden que se puede defender.
3. **El costo de equivocarse es asimétrico.** Si el trailing va último y sale no medible,
   queda apagado como NO EVALUADA y vuelve el día que haya más datos, con las otras cuatro ya
   decididas. Si va primero y gana, las otras cuatro quedan sin decidir **y sin registro de
   por qué**, porque el motivo no sería la capa sino el orden.

**El orden del torneo queda entonces así**, y va registrado con el resultado como exige la
sección de abajo:

    break_even → time_stop → giveback → trailing_stop → reversal → market_regime

Una consecuencia que hay que escribir porque invierte una frase del loteo: la tabla de 2C
decía que `giveback` se mide **contra el trailing ya fijo**. Ahora es al revés — `giveback`
va antes y el trailing se mide contra ella. El "si dos capas hacen lo mismo, se elige una"
sigue siendo un número y no una frase; lo que cambió es cuál de las dos tiene que probar que
agrega algo sobre la otra, y le toca a la que tiene más parámetros.

#### Cuántas capas decide cada universo

*(Agregado al cerrar 2A+2B y recalculado dos veces. La primera, cuando el informe v3 mostró
que la proyección se había corrido sobre la línea base equivocada. La segunda, el
2026-09-13, cuando el trailing dejó de ser línea base y la "equivocada" pasó a ser la
buena. La segunda vuelta no es una ironía: es la consecuencia aritmética de la decisión, y
el número que la motivó es justamente el de la primera.)*

El cálculo de poder por capa se hizo sobre los fixtures, que dan 30 trades (4 símbolos,
5 años) y 73-75 (10 símbolos, 5 años). Lo que faltaba contestar es qué pasa con el universo
que la Fase 3 va a tener de verdad, y ahora tiene respuesta **por opción de universo** en
vez de a ojo: `scripts/universo.py` ata las dos puntas, porque *n* no se elige —sale de
símbolos × años × ritmo de señales— y el MDE va con 1/√(f·n), así que proyectar es
aritmética. Misma *f*, mismo σ, mismo efecto disponible, y solo cambia *n*.

    python scripts/universo.py --plantilla config/strategies/ema_cross_sin_trailing.yaml

##### El número que motivó el cambio de línea base (histórico, ya aplicado)

**La proyección original se corrió sobre `ema_cross_sin_trailing.yaml`, y en ese momento esa
no era la línea base.** El PLAN declaraba que las plantillas arrancan con hard stop **+
trailing**, así que la configuración contra la que el torneo iba a medir era la v3, con el
chandelier prendido. Y la línea base no es un detalle de la corrida: **define cuánta R queda
sobre la mesa para que las otras capas la capturen**. Un trailing que corta los trades antes
se lleva puesto justo el efecto disponible de las capas de salida que vienen después.

Esta tabla es la que hizo caer la regla. Quedó como evidencia de la decisión, no como estado
actual: desde el 2026-09-13 la columna "sin trailing" **es** la línea base y el trailing
compite.

Las dos tablas, a n=230, con la misma aritmética y lo único distinto siendo qué corrida
generó los trades:

| capa | indep. SIN trailing | indep. **CON trailing** | corr. SIN trailing | corr. **CON trailing** |
|---|---|---|---|---|
| `trailing_stop` (entonces línea base, no competía) | 23% | 20% | 21% | 22% |
| `time_stop` | **23%** | 66% | **27%** | 43% |
| `giveback` | 42% | 56% | 32% | 59% |
| `market_regime` | 34% | 50% | 54% | 83% |
| `break_even` | 55% | **NO medible** | 67% | **NO medible** |
| `reversal` | no estimable sin la capa escrita | ídem | ídem | ídem |
| `event_risk` | no estimable sin red | ídem | ídem | ídem |

"Exigencia" es `MDE por trade afectado / efecto disponible`: qué fracción del **mejor
caso** —capturar toda la R que el trade dejó sobre la mesa— tiene que lograr la capa, en
cada trade que toca, para que el resultado se distinga de un empate. El criterio para
leerla no es el flag binario `medible`: ese flag es condición necesaria y nada más.
Ninguna capa real captura su mejor caso —un chandelier devuelve 3 ATR antes de sacarte, un
break-even sale exactamente en cero cuando el trade habría vuelto—, así que **una exigencia
por encima de ~1/3 no es una capa medible: es una capa a la que le vamos a pedir un
milagro y vamos a leer el empate como "no aporta"**.

##### El mecanismo: el trailing no agrega ruido, saca efecto disponible

Lo que se mueve entre las dos tablas no es el ruido. El σ del efecto **baja** con el
trailing prendido (1.43R → 1.18R en el independiente, 1.39R → 1.20R en el correlacionado),
porque el chandelier comprime la distribución de resultados, y por eso el MDE por trade
afectado también baja (0.33R → 0.27R para `time_stop`). Lo que se derrumba es el
denominador:

| capa | efecto disponible SIN trailing | CON trailing |
|---|---|---|
| `break_even` | 0.99R | **0.16R** |
| `time_stop` | 1.63R | 0.69R |
| `giveback` | 1.40R | 0.64R |

O sea: **medir se volvió más fácil y no alcanzó, porque quedó mucho menos para medir.** El
trailing se come la R que las otras capas de salida tenían para capturar — que es lo
esperable, porque todas hacen la misma cosa (sacarte antes) y compiten por el mismo
recurso.

##### Con aquella línea base no quedaba ninguna capa medible

Con el corte de 1/3 y las capas del torneo de entonces:

- **No se decidía ninguna de las cuatro estimables.** `time_stop`, que era la única que
  pasaba holgada en los dos universos (23/27%), se iba a 66/43%. `giveback` a 56/59%,
  `market_regime` a 50/83%, y `break_even` dejaba de ser medible incluso con el flag
  binario: su efecto disponible (0.16R indep., 0.27R corr.) era **menor que el MDE**, así
  que no se distinguía del ruido ni capturando el 100% del mejor caso.
- **Quedaba una capa por evaluar y sin proyectar**: `reversal`, que no tiene número porque
  la capa no está escrita.
- **Y `event_risk` seguía afuera** por la red, con su decisión ya escrita.

O sea: **con la línea base que iba a estar corriendo, el torneo de la 2C se reducía a
evaluar una sola capa, y era justo la única que no se podía dimensionar de antemano.** Un
torneo de una capa no es un torneo: es una comparación A/B, que es lo que el banco ya hace.
Ese es el costo que la decisión del 2026-09-13 dejó de pagar.

##### Esto confirma, con un caso, que el orden del torneo decide el resultado

Ya estaba escrito que "el resultado del torneo depende del orden, así que el orden se
registra con el resultado". Acá hay el caso concreto que lo demuestra, y es más fuerte que
la frase: **la línea base no cambia el ranking de las capas, cambia cuáles son medibles.**
Con `trailing_stop` apagado, `time_stop` necesita capturar el 23% y es la mejor candidata
del torneo. Con `trailing_stop` prendido —que es la misma decisión de siempre, tomada por
diseño y no medida— `time_stop` necesita el 66% y sale del torneo sin haber sido evaluada.

La consecuencia operativa, que va más allá de este caso: **cada capa que se prende reduce
el poder disponible para todas las que vienen después**, porque se lleva parte del efecto
que quedaba por capturar. El torneo no es "medir seis capas", es "gastar un presupuesto de
efecto disponible en un orden", y el orden hay que elegirlo sabiendo eso. Prender primero
la capa más agresiva —que es lo que el PLAN hacía con el chandelier de 3 ATR— es gastar el
presupuesto antes de empezar. **Esa es la consecuencia que se resolvió el 2026-09-13**: el
trailing pasó a competir y entra cuarto, no primero, para no repetir el mismo error desde
adentro del torneo. El argumento y las dos opciones evaluadas están en "El trailing dejó de
ser línea base".

##### La proyección rehecha con la línea base nueva

Con hard stop + take profit como línea base, el efecto disponible de cada capa vuelve a los
valores "sin trailing". Pero no es lo único que cambia, y lo otro va en la dirección
contraria, así que las dos cosas juntas.

**Lo que mejora: el denominador vuelve.** El efecto disponible de cada capa, medido sobre
los mismos fixtures y lo único distinto siendo qué corrida generó los trades:

| capa | disponible CON trailing | **disponible con la línea base nueva** |
|---|---|---|
| `break_even` | 0.16R / 0.27R | **0.99R / 0.77R** |
| `time_stop` | 0.69R / 1.02R | **1.63R / 1.32R** |
| `giveback` | 0.64R / 0.70R | **1.40R / 1.64R** |
| `market_regime` | 1.67R / 0.87R | **2.96R / 1.53R** |

*(indep. (4) / corr. (10). El σ sube en la misma corrida —1.18R → 1.43R y 1.20R → 1.39R—
porque el chandelier ya no comprime la distribución, así que el MDE empeora; lo que manda es
que el disponible sube más.)*

**Lo que empeora: el cupo de cartera pone un techo más bajo.** Sin trailing los trades duran
**29 velas en vez de 17**, y el cupo de cinco posiciones simultáneas es un techo que no
depende del universo: `5 / (29/252) ≈ 44` trades por año, o sea **662 en 15 años, haya 13
símbolos o 40**, contra 1141 con el trailing prendido. Ampliar el universo deja de comprar
*n* mucho antes que con la línea base vieja. Es un techo optimista además: supone las señales
repartidas en el tiempo, y las de un universo correlacionado llegan juntas.

**Las tres opciones, con la línea base nueva** (15 años, ritmo de 1.75 trades por
símbolo-año):

| opción | símb | símb-año útil | señales | n con cupo | ¿el cupo corta? |
|---|---|---|---|---|---|
| 13 ETFs (sectoriales + SPY/QQQ/IWM) | 13 | 180 | 315 | **315** | no |
| 13 ETFs + 20 acciones líquidas | 33 | 464 | 813 | **662** | sí, desde 813 |
| 40 acciones | 40 | 568 | 996 | **662** | sí, desde 996 |

**Cuántas capas quedan estimables en cada una.** La exigencia proyectada, con el corte de
1/3 de §2.2, y **por duplicado sobre los dos fixtures**, porque *f*, σ y el efecto
disponible salen de ahí y la distancia entre los dos es la incertidumbre real de la tabla
(un `*` marca que pasa el corte):

| capa | 13 ETFs · n=315 | 33 ó 40 símbolos · n=662 | *(referencia: con trailing, n=323)* |
|---|---|---|---|
| `trailing_stop` | 20%\* / 18%\* | 14%\* / 12%\* | *17%\* / 18%\* — pero no competía* |
| `time_stop` | 19%\* / 23%\* | 13%\* / 16%\* | *55% / 37%* |
| `giveback` | 36% / 27%\* | 25%\* / 19%\* | *48% / 50%* |
| `market_regime` | 29%\* / 46% | 20%\* / 32%\* | *43% / 70%* |
| `break_even` | 47% / 57% | 33%\* / 40% | *NO medible / NO medible* |
| `reversal` | no estimable sin la capa escrita | ídem | ídem |
| `event_risk` | no estimable sin red | ídem | ídem |

*(indep. (4) / corr. (10).)*

| opción | capas bajo el corte, indep. | corr. | **en las que coinciden** |
|---|---|---|---|
| 13 ETFs · n=315 | 3 | 3 | **2**: `trailing_stop`, `time_stop` |
| 33 ó 40 símbolos · n=662 | 5 | 4 | **4**: + `giveback`, `market_regime` |
| *(con trailing, n=323)* | *1* | *1* | *1, y era la que no competía → **0*** |

##### El panorama mejora, y con el número; y aun así queda escaso

**Mejora, y mucho.** Con la línea base vieja el torneo decidía **cero** capas con cualquiera
de los tres universos al alcance: la única que pasaba el corte a n=323 era el propio
trailing, que no competía. Con la línea base nueva y el universo **más barato de los tres**
—13 ETFs, sesgo de supervivencia casi nulo, 2.6 MB de CSV— el torneo decide **dos capas con
los dos fixtures de acuerdo, y tres con cada uno por separado**. `break_even`, que con el
trailing prendido no se distinguía del ruido ni capturando el 100% de su mejor caso, pasa a
tener una exigencia finita (47-57%): sigue sin entrar, pero ahora queda **NO EVALUADA con un
número y una distancia medible** en vez de como una imposibilidad aritmética. Ese es
exactamente el cambio que la decisión compró.

**Y aun así queda escaso, y hay que decirlo igual de fuerte.** Dos capas decididas de seis
no es un torneo holgado, y las dos que quedan afuera con los dos fixtures de acuerdo
—`break_even` siempre, `market_regime` en el correlacionado— son justo las que trabajan en
las rachas malas, que es donde más falta hace saber si aportan. La lectura honesta es que
**13 ETFs alcanza para que el torneo exista, no para que decida todo.**

**Lo que esto decide sobre el universo, que era la pregunta.** El cupo de cartera cambia la
respuesta respecto de la línea base vieja:

- **Ampliar de 13 ETFs a 33 símbolos compra una capa**, `market_regime`, y la compra justo
  en el borde: 32% contra un corte de 33%, sobre una tabla cuyos dos fixtures discrepan por
  factores de dos (`time_stop` al 33% pide 907 trades con el independiente y 398 con el
  correlacionado). Una capa que entra por 1.3 puntos porcentuales en esa tabla no entra: la
  precisión de la tabla no llega hasta ahí.
- **Ampliar de 33 a 40 no compra nada**: las dos opciones dan el mismo n = 662, porque el
  cupo corta antes. Los símbolos de más solo agregan señales rechazadas.
- Y las 20 acciones se pagan con **sesgo de supervivencia**, que es el que el PLAN marca
  como el que no se arregla del todo, y en la dirección peor: un universo de sobrevivientes
  tiene menos rachas malas, que son los trades donde `break_even` y `market_regime` tendrían
  algo que hacer. O sea que se paga sesgo justo en las dos capas que se querían comprar.

**Conclusión: 13 ETFs**, sabiendo qué compra —el torneo con dos o tres capas decidibles— y
qué no —`break_even`, que necesita bastante más que un universo más grande—. Si algún día se
quiere más *n*, el camino barato no es más símbolos sino **más período** (25 años sobre los
mismos ETFs no agrega sesgo de selección, aunque mete dos regímenes adentro del in-sample) o
**subir `max_open_positions`**, que es lo que destraba el techo de 662 y hoy es el que ata.

##### Las dos etiquetas que hay que arrastrar con esta tabla

1. **El ritmo de 1.80 —ahora 1.75— trades por símbolo-año está medido sobre fixtures
   SINTÉTICOS**, y *toda* la tabla de universos descansa en ese número: es el que convierte
   símbolos y años en *n*. Los ETFs sectoriales tienen **menos volatilidad** que estas series
   sintéticas, y un cruce de medias sobre una serie menos volátil cruza menos veces, así que
   el ritmo real probablemente sea **más bajo** y la columna *n* sea **optimista**. Por eso
   `universo.py --ritmo` existe: cuando se mida el ritmo real bajando tres o cuatro símbolos,
   la tabla se rehace sin tocar código.
2. **El efecto disponible de cada capa también sale de los sintéticos.** Con la línea base
   nueva cambia el denominador —que es el punto de toda esta sección— pero el generador sigue
   siendo el mismo `_ohlcv_from_shocks` de siempre, y las capas de salida explotan justamente
   la estructura que un random walk no tiene (retrocesos con memoria, volatilidad agrupada).
   La aritmética sobre *n* es exacta; los insumos valen lo que dice la etiqueta de alcance de
   `ESTADO.md` §2: **sirven para elegir el universo, no para decidir una capa.**

Lo que **no** depende de los sintéticos, y por eso sobrevive a las dos etiquetas, es el
mecanismo: que la línea base consume efecto disponible y que cada capa que entra deja menos
para las que siguen. Eso es aritmética de qué le queda a la capa siguiente, no una propiedad
del generador.

> **Corrección (2026-09-15) — el ritmo real y la palanca, medidos.** Toda la tabla de arriba
> (1.75 t/símbolo-año, n=315 con los 13 ETFs, "subir `max_open_positions` es el camino barato")
> es la primera etiqueta de esta sección aplicada tal como avisaba: son insumos sintéticos, y
> el número real resultó más bajo. Medido con `ema_cross_sin_trailing` sobre los 13 ETFs
> reales (`tests/fixtures/real`, cash ya corregido — "Cash real: antes de medir nada", más
> arriba): **1.30 trades por símbolo-año, no 1.75** (un 26% menos, en la dirección que la
> etiqueta ya predecía), **249 trades totales y 155 in-sample**, no 315.
>
> Y la palanca que este párrafo proponía —subir `max_open_positions`— **no es la que ata**.
> Sobre los 13 ETFs reales, de 74 señales rechazadas 43 son por falta de cash (`no hay cash
> para comprar ni 1 acción` + `sin cash al momento del fill`) contra 31 por cupo: sacar el
> cupo del medio (`max_open_positions: 99`) compra 11 trades, no destraba nada parecido al
> techo de 662 que esta sección calculaba. El techo por cupo es real —la aritmética de
> `techo_por_cupo` no depende de qué fixture se use— pero sobre este universo y este período
> el cash llega antes que el cupo, así que subir el cupo solo no compra el *n* que esta
> sección asumía. `tests/test_universo.py` y `ESTADO.md` §"Cash real" fijan los números
> nuevos. La conclusión de universo (13 ETFs, sesgo casi nulo) **no cambia**: lo que cambia es
> con qué *n* hay que planear el torneo, y que la próxima palanca a probar, si hace falta más
> *n*, es más cash o más período, no más cupo.

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
