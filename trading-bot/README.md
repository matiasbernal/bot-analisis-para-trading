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
3. **Concentración del resultado.** Cuánto del P&L viene de los 5 mejores trades.
   Si es el 80%, tuviste suerte dos veces.
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
