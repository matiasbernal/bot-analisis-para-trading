# tradingbot — análisis de trading swing sobre acciones y ETFs

Herramienta para analizar momentos de entrada y salida con parámetros propios, y
para **validar esos parámetros contra datos históricos antes de arriesgar plata**.
No ejecuta órdenes: analiza, avisa y mide.

El diseño completo está en [`PLAN.md`](PLAN.md). Esto es la **tanda 1** (Fases 0,
1 y 2): la capa de datos, los indicadores y un motor de backtest validado.

## Qué hay y qué no

| Funciona hoy | Llega en la tanda 2 |
|---|---|
| Datos: Yahoo, Stooq, CSV locales, cache parquet, validación | Earnings, régimen de mercado |
| Indicadores: SMA, EMA, RSI, MACD, ATR, Bollinger, ADX | Estocástico, ROC, OBV, donchian |
| Reglas por YAML: 11 operadores, composición `all`/`any`/`not` | Filtros de entrada (liquidez, earnings) |
| Salidas: **hard stop** y **take profit** | Trailing, break-even, reversión, giveback, time stop |
| Riesgo por trade: sizing por 1R, tope de concentración | Riesgo de cartera: heat, grupos, cortacircuito |
| Backtest con costos, métricas, benchmark, manifiesto | `scan`, journal, Telegram, web, optimización |

## Instalar

Python 3.11 o superior.

```bash
cd trading-bot
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # en Windows: .venv\Scripts\pip
.venv/bin/playwright install chromium  # solo para el test responsive del informe
```

## Correr un backtest

Sobre los fixtures sintéticos que vienen en el repo (no necesita internet):

```bash
tradingbot backtest --strategy config/strategies/ema_cross.yaml --data tests/fixtures/
```

Con informe HTML y manifiesto:

```bash
tradingbot backtest --strategy config/strategies/ema_cross.yaml \
                    --data tests/fixtures/ \
                    --report reports/ema_cross.html \
                    --manifest reports/ema_cross.json
```

Sobre datos reales (necesita internet; copiá `config/settings.example.yaml` a
`config/settings.yaml` primero):

```bash
tradingbot backtest --strategy config/strategies/ema_cross.yaml --symbol SPY
```

Opciones: `--symbol` restringe el universo, `--offline` usa solo el cache,
`--plotly cdn` genera un HTML liviano que necesita internet para dibujar
(el default, `inline`, embebe Plotly y abre sin conexión).

## Generar los fixtures reales (en tu máquina)

**Los fixtures que vienen en el repo son sintéticos, no datos de mercado.**
`tests/fixtures/synthetic/{AAPL,MSFT,SPY,QQQ}.csv` son random walks
determinísticos etiquetados con nombres de ticker para que las plantillas corran
sin red. Sirven para probar el motor; no se puede concluir nada sobre ninguna
estrategia a partir de ellos, y el informe los rotula como "serie SINTÉTICA".

Hay **dos** universos sintéticos, y la diferencia importa:

| Carpeta | Qué es | Para qué |
|---|---|---|
| `tests/fixtures/synthetic/` | 4 series **independientes** entre sí (ρ ≈ −0.01) | El universo de la tanda 1. Sus números están fijados en los tests. |
| `tests/fixtures/correlated/` | 8 series **correlacionadas por grupos**: tech, energía, defensivo y el índice (ρ 0.85 intragrupo, 0.35 entre grupos, 0.70 contra SPY) | Todo lo que dependa de cómo se mueven juntas: heat de cartera, `max_per_group`, gaps simultáneos (tanda 2). |

Por qué hacen falta los dos: sobre las series independientes, una cartera de
cuatro símbolos muestra **la mitad** del drawdown de sus componentes, y esa
reducción es puro artificio del generador. Sobre las correlacionadas muestra el
86% del promedio, que es lo que pasa en el mercado real. Cualquier control de
riesgo de cartera probado sobre las primeras se vería el doble de bueno de lo
que es.

El sandbox donde se construyó esto no llega a Yahoo ni a Stooq. Los CSV reales
los generás vos, una vez, y se commitean:

```bash
python scripts/fetch_fixture.py SPY AAPL          # ~3 años a tests/fixtures/
python scripts/fetch_fixture.py SPY --years 10    # más historia
```

Hasta que existan, los tests que los usan se saltean con el motivo. Los
sintéticos (`tests/fixtures/synthetic/`) son determinísticos y ya están; se
regeneran con `python scripts/make_synthetic_fixtures.py`.

## Leer el informe

El orden en que conviene mirarlo:

1. **El semáforo.** Con menos de 30 trades el informe avisa en grande que no se
   puede concluir nada; con menos de 100, que las conclusiones son débiles.
2. **La columna de buy & hold.** Está al lado de cada métrica. Una estrategia que
   rinde menos que comprar y esperar no sirve, por linda que sea la curva.
3. **Concentración del resultado.** "5 mejores vs. lo normal": cuánto aportan los
   cinco mejores ganadores comparado con lo esperable para esa cantidad de
   ganadores. 1.00× es normal; 1.30× significa que el resultado depende de un
   puñado de operaciones. Con menos de 10 ganadores el informe avisa que el
   número no se puede interpretar.
4. **Racha máxima de pérdidas.** No es para el backtest, es para vos: si el
   histórico muestra 9 pérdidas seguidas, en vivo las vas a vivir.
5. **Salidas por regla.** Qué porcentaje salió por stop, por objetivo y por señal,
   con el resultado medio de cada grupo.
6. **In-sample / out-of-sample.** El tramo final se mira una vez, al final.

El HTML está diseñado para el celular: una columna, gráficos que se adaptan,
tablas que scrollean solas, modo oscuro según el sistema.

Tres cosas que el informe dice y conviene no pasar por alto:

- **Si el rango del YAML no coincide con los datos**, lo avisa ("RANGO
  RECORTADO"). Pedir 2010-2025 y correr 2018-2022 cambia todo lo que sigue.
- **Las posiciones abiertas al cierre del período** van aparte y no cuentan como
  trades: no las cerró ninguna regla.
- **De dónde salió cada serie** está rotulado (sintética, CSV local, Yahoo).

> **Alcance**: el informe es de la tanda 1. Cuando llegue la Fase 3 con el
> contrafáctico, la atribución completa y el análisis MAE/MFE, la plantilla va a
> cambiar y **la verificación responsive (390/412/1280 px) hay que repetirla**.
> Lo mismo cuando se agreguen las capas de salida: la tabla de atribución va a
> tener más filas y un trade va a poder salir por varias reglas a la vez.

## Las reglas de rigor (no negociables)

1. **Sin lookahead.** El indicador en `t` usa solo datos hasta `t`. La señal se
   evalúa al cierre de `t` y se ejecuta en la apertura de `t+1`.
   `tests/test_no_lookahead.py` lo verifica de cuatro formas distintas.
2. **Precios ajustados** por splits y dividendos (`auto_adjust=True`).
3. **Costos siempre**: comisión y slippage en cada entrada y en cada salida.
4. **Stop conservador**: si en una vela se tocan stop y objetivo, gana el stop.
   Si la vela abre con gap por debajo del stop, el fill es en la apertura.
5. **Benchmark obligatorio**: buy & hold del mismo universo, en todo informe.
6. **Out-of-sample reservado**: se afina sobre el in-sample; el resto se toca una vez.
7. **Reproducibilidad**: cada corrida guarda un manifiesto con el YAML exacto, el
   hash de los datos y el commit. Dos corridas dan el mismo archivo.

## La unidad de riesgo (1R) — leer antes de la Fase 3

**1R no vale lo que dice el YAML.** `risk_pct: 1.0` sobre $10.000 declara $100
por trade, pero el riesgo que termina teniendo cada posición es
`acciones × riesgo por acción`, y eso es menos: el tamaño se redondea a acciones
enteras y, cuando el tope de concentración ata, recorta la posición. Medido
sobre la plantilla `ema_cross` y el fixture (`scripts/riesgo_realizado.py`):

```
min 0.83R   media 0.95R   max 1.00R    con max_position_pct: 30 (la plantilla actual)
min 0.54R   media 0.78R   max 0.99R    con max_position_pct: 20 (antes del bloque 2)
```

Nunca por encima de 1R: el motor arriesga menos de lo declarado, jamás más.

De ahí salen tres reglas que el resto del proyecto tiene que respetar:

1. **La expectancy del plan sigue siendo la media de `pnl_r`** — "cuánto deja un
   trade típico", cada trade pesando igual. No se toca. Lo que **no** se puede
   hacer es traducirla a plata multiplicando por el 1R declarado: con el tope en
   20% esa cuenta daba $25.09 por trade cuando el promedio real era $17.27, un
   45% de más. Por eso el informe imprime las tres cosas juntas —expectancy en R,
   expectancy en plata y el 1R realizado promedio— y avisa cuando la lectura
   ingenua se desvía.

2. **Retorno sobre riesgo desplegado** (`Σ pnl / Σ riesgo real`) es otra métrica,
   no un reemplazo: pondera cada trade por la plata que puso en juego. Responde
   "cuánto devolvió cada peso arriesgado", que es la pregunta del riesgo de
   cartera, no la de la calidad de la regla.

3. **El heat de cartera de la Fase 3 se calcula en pesos, no contando R
   nominales**:

   ```
   heat = Σ(riesgo real de las posiciones abiertas) / equity
   ```

   `max_portfolio_heat_r: 4.0` significa **4% del equity en riesgo abierto**, y
   se compara contra esa suma. Contar "cuatro posiciones de 1R" daría 4R
   nominales que en la práctica son ~3.1R, y el cortacircuito quedaría
   calibrado sobre una unidad que no es la que dice. Lo mismo vale para el
   riesgo que muestre la alerta y para cualquier lectura tipo "cinco pérdidas
   seguidas son −5R", que está inflada en la misma proporción: el informe
   publica el costo de la peor racha en plata justamente por eso.

Cada `Trade` guarda `risk_amount` (el 1R realizado) y `risk_target` (el
declarado al momento de la señal). Los dos van a la tabla de trades y al journal.

### Qué puede decir la alerta (decisión para la Fase 4)

El plan define una alerta que imprime `Riesgo: 1.0R = $101`. Con la unidad real
eso hay que reescribirlo, y la buena noticia es que **el riesgo en pesos sí se
conoce la noche anterior**: la cantidad de acciones y el riesgo por acción se
fijan al cierre de la señal, así que `acciones × riesgo por acción` es un número
exacto antes de mandar la orden. Lo que **no** se conoce es el precio del stop,
que se ancla al fill de la apertura.

Formato decidido para la Fase 4 (todavía sin implementar):

```
🟢 ENTRADA · MSFT
Mañana en apertura (orden MOO)

Comprar: 13 acciones
Riesgo:  $98.21  (0.98R de $100 declarado)
Stop:    apertura − $7.55 por acción
         ≈ $142.04 si abre como cerró
Target:  apertura + $22.66  (3R)
```

Reglas del formato:

- **El riesgo en pesos va exacto, sin "~"**, porque lo es. Al lado, cuánto es
  contra el 1R declarado, para que se vea si el tope recortó la posición.
- **El stop y el objetivo van como distancia, no como precio**: el precio exacto
  depende de la apertura, y darlo redondo invita a cargar una orden de stop al
  número equivocado. El precio estimado va abajo, marcado como estimación.
- **Única excepción al "exacto"**: si el cash no alcanza al momento del fill, el
  motor recorta las acciones. La alerta lo aclara cuando la posición usa más del
  90% del cash disponible.

### Cuándo `risk_pct` deja de decidir, y el sesgo que eso mete

El tamaño sale del menor de tres números: el que pide el riesgo, el que permite
`max_position_pct` y el que alcanza el cash. Igualando los dos primeros:

> **el tope manda cuando la distancia al stop, en % del precio, es menor que
> `risk_pct / max_position_pct`.**

Con `risk_pct: 1.0` y `max_position_pct: 20` ese umbral es 5%, y un stop de
2×ATR sobre estos papeles está a ~4.4%: el tope ataba 21 de 31 trades y
`risk_pct` no decidía nada. Por eso las plantillas usan `max_position_pct: 30`
(umbral 3.33%), y por eso **el motor avisa** cuando la combinación vuelve a
dejar a `risk_pct` decorativo, e imprime en cada informe quién decidió el tamaño:

```
  Quién decidió el tamaño    riesgo 30, tope 1, cash 0 (de 31 señales)
```

**El sesgo que esto mete, y que ninguna opción evaluada arregla**: el tope ata
cuando el stop está cerca, y el stop está cerca cuando el ATR es bajo. O sea que
el motor arriesga **menos en los trades tranquilos y 1R completo en los
volátiles**, que es exactamente al revés de lo deseable. Medido sobre el fixture:

| tope | correlación riesgo↔distancia al stop | tercio de stops cercanos | tercio de lejanos |
|---|---|---|---|
| 20% | +0.92 | 0.596R | 0.938R |
| 30% | +0.06 | 0.941R | 0.943R |

Con el tope en 30% el sesgo está **dormido**, no resuelto: vuelve apenas el tope
vuelva a atar (cuenta más chica, papeles más caros, stops más ajustados,
`risk_pct` más alto). `test_riesgo_realizado.py` fija las dos mediciones para que
se note si reaparece.

## El cotejo contra `backtesting.py`

El motor es propio, así que se coteja contra una implementación independiente:
la misma estrategia de cruce de medias en `backtesting.py` y acá
(`tests/test_vs_backtesting.py`). **El cotejo que cuenta para la definición de
terminado es el de comisión sola**, en dos escenarios: sin costos y con
comisión del 0.05% por lado. En los dos, los cuatro símbolos quedan dentro del
5% en CAGR, cantidad de trades y max drawdown.

El slippage no se compara directo, y no es un detalle: el `spread` de
`backtesting.py` se cobra **una vez por ida y vuelta** (ajusta la entrada y deja
la salida sin tocar), mientras que nosotros lo aplicamos **en cada punta**, que
es lo que exige la regla de rigor 3. Con `spread` activado el desvío de CAGR
llega al 5.5% en SPY, y eso mide la diferencia entre los dos modelos, no un bug
nuestro. Si dentro de seis meses ves un cotejo con spread que "falla", es este
párrafo.

Lo que queda de diferencia son dos decisiones nuestras, deliberadas:

- **El sizing se calcula al cierre de la barra de la señal**, con `close[t]`
  como estimación del precio de entrada, porque es lo único que se sabe cuando
  se manda una orden market-on-open; en el fill solo se recorta si el cash no
  alcanza. `backtesting.py` dimensiona en el fill, con `open[t+1]` ya conocido,
  y por eso a veces entra con una acción más.
- **La posición que sigue abierta cuando se acaban los datos se liquida al
  cierre de la última vela** (consistente con la curva de equity, que es
  mark-to-market al cierre). `backtesting.py` la cierra en la apertura de esa
  vela. Ese trade no cuenta como operación del sistema: se reporta aparte.

## El archivo de estrategia

Todo lo que se toca vive en el YAML; nada queda hardcodeado. Las plantillas están
en `config/strategies/`:

```yaml
indicators:
  ema_fast: {type: ema, source: close, period: 20}
  atr:      {type: atr, period: 14}

entry:
  all:
    - {left: ema_fast, op: crosses_above, right: ema_slow}
    - {left: close,    op: ">",           right: sma_trend}

exits:
  signal:      {any: [{left: ema_fast, op: crosses_below, right: ema_slow}]}
  hard_stop:   {mode: atr, multiple: 2.0}
  take_profit: {mode: rr, ratio: 3.0}

execution:
  signal_on: close        # la regla se evalúa con la vela CERRADA
  fill_on:   next_open    # la orden se ejecuta en la apertura siguiente
  commission_pct: 0.05
  slippage_pct:   0.05
```

Operadores: `>`, `<`, `>=`, `<=`, `==`, `crosses_above`, `crosses_below`,
`between`, `rising`, `falling`, `pct_change_gt`. Los indicadores de varias
salidas se referencian con punto (`macd.hist`, `bb.upper`).

### Plantillas

| Archivo | Qué es |
|---|---|
| `ema_cross.yaml` | Cruce de medias con filtro de tendencia. La del plan. |
| `rsi_pullback.yaml` | Retroceso sobre tendencia alcista. La del plan. |
| `breakout_52w.yaml` | **Pendiente.** Ruptura del máximo de 52 semanas: necesita el indicador `donchian`, que llega en la tanda 2. El slot queda vacío a propósito. |
| `extra_bollinger_upper_break.yaml` | Extra, no está en el plan. Ruptura de la banda superior de Bollinger. **No reemplaza a `breakout_52w`**: el máximo móvil es momentum y Bollinger es reversión a la media. |

Lo que todavía no existe se **rechaza con un mensaje que lo dice**: poner
`trailing_stop:` hoy no se ignora en silencio, falla explicando que es de la
tanda 2. Un backtest que ignora en silencio la mitad de tu configuración miente.

## Tests

```bash
pytest -v                  # todo
pytest tests/test_no_lookahead.py -v
pytest -m "not network"    # sin los que necesitan internet
pytest -m "not playwright" # sin los que necesitan navegador
```

Los tests responsive usan el Chromium que instala `playwright install chromium`.
Si ya tenés uno en otro lado (contenedor, CI), apuntá la variable en vez de
bajar otro:

```bash
TRADINGBOT_CHROMIUM=/ruta/al/chromium pytest tests/test_report_responsive.py
```

Los que necesitan red detectan conectividad y se saltean con el motivo; los que
usan los CSV reales se saltean hasta que los generes.

## Estructura

```
tradingbot/
  config.py          carga YAML + valida con pydantic (errores claros, no KeyError)
  data/              provider ABC, yahoo, stooq, csv local, cache parquet, validación
  indicators/        trend, momentum, volatility + registry ("ema" -> función)
  strategy/          conditions, engine (all/any/not), risk (sizing), position, exits
  backtest/          engine (loop barra a barra), portfolio, costs, metrics, manifest
  reporting/         informe de consola y HTML mobile-first con gráficos Plotly
  cli.py             typer: backtest
```

Las capas no se saltean: `data -> indicadores -> reglas -> backtest -> salida`.
