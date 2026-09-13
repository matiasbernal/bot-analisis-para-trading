# tradingbot — análisis de trading swing sobre acciones y ETFs

Herramienta para analizar momentos de entrada y salida con parámetros propios, y
para **validar esos parámetros contra datos históricos antes de arriesgar plata**.
No ejecuta órdenes: analiza, avisa y mide.

El diseño completo está en [`PLAN.md`](PLAN.md). Hoy están la tanda 1 (Fases 0, 1
y 2: datos, indicadores y un motor de backtest validado) y las tandas **2A** —
estado de la posición, banco A/B, poder de medición por capa y trailing
chandelier— y **2B** — riesgo de cartera. Falta la **2C**, el torneo de capas,
que está parada esperando datos reales por el motivo de
[`ESTADO.md`](ESTADO.md) sección 2, no por falta de código.

> **¿Llegás sin contexto?** [`ESTADO.md`](ESTADO.md) cuenta dónde está el
> proyecto, qué se decidió después de cerrar la tanda 1 y **por qué** cada cosa
> es como es. Empezá por ahí.

## Qué hay y qué no

| Funciona hoy | Llega después |
|---|---|
| Datos: Yahoo, Stooq, CSV locales, cache parquet, validación | Earnings, régimen de mercado (2C) |
| Indicadores: SMA, EMA, RSI, MACD, ATR, Bollinger, ADX | Estocástico, ROC, OBV, donchian |
| Reglas por YAML: 11 operadores, composición `all`/`any`/`not` | Filtros de entrada (liquidez, earnings) |
| Salidas: **hard stop**, **trailing chandelier** y **take profit** | Break-even, reversión, giveback, time stop (2C) |
| Riesgo por trade: sizing por 1R, tope de concentración | |
| **Riesgo de cartera**: heat en pesos, límite por grupo, dos cortacircuitos | |
| Banco A/B con bootstrap pareado y poder de medición por capa | El torneo que los usa (2C) |
| Backtest con costos, métricas, benchmark, manifiesto | `scan`, journal, Telegram, web, optimización |

> **El trailing está prendido por diseño, no porque se haya medido que aporta.**
> El PLAN lo declara línea base de las plantillas, así que no compite en el
> torneo. Con los datos que hay, el poder de medición no alcanza para afirmar
> que suma ni que resta, y el informe lo dice cada vez que el trailing aparece.

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

Comparar dos configuraciones sobre los mismos datos (el banco A/B del torneo de
capas: empareja los trades por símbolo y fecha de entrada y devuelve el delta
**con su incertidumbre**, que es lo que convierte "mejora la expectancy" en una
medición):

```bash
tradingbot comparar --base config/strategies/ema_cross_sin_trailing.yaml \
                    --variante config/strategies/ema_cross.yaml \
                    --data tests/fixtures/synthetic
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
| `tests/fixtures/correlated/` | 10 series **correlacionadas por grupos**: tech (4), energía (3), defensivo (2) y el índice (ρ 0.85 intragrupo, 0.35 entre grupos, 0.70 contra SPY) | Todo lo que dependa de cómo se mueven juntas: heat de cartera, `max_per_group`, gaps simultáneos (tanda 2). |

Por qué hacen falta los dos: sobre las series independientes la volatilidad de
la cartera es el **32%** de la de sus componentes (pura diversificación de
ruido), contra **78%** en el universo correlacionado. El drawdown de la cartera
correlacionada es **2.2×** el de la misma cartera sin correlación. Cualquier
control de riesgo de cartera probado sobre las primeras se vería mucho mejor de
lo que es.

Los tamaños de grupo tampoco son casuales: con dos símbolos por sector,
`max_per_group: 2` no se puede violar nunca y el control queda sin test. Con un
grupo de 4 y otro de 3, el fixture produce 166 días-grupo con tres o más
posiciones abiertas del mismo sector (32 con cuatro o más) sobre un cruce de
medias corriente: eso es lo que la Fase 3 va a tener que rechazar.

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

### La regla del cociente inestable

Un número del informe que sea un cociente se publica **solo si el denominador
aguanta el peso**. Salió de que el mismo error apareció tres veces con tres caras
—concentración 252%, error de lectura ingenua 426%, diferencia de CAGR 118% sobre
30 puntos básicos— y las tres se arreglaron por separado antes de que alguien
notara que era el mismo error. La regla, en orden:

1. **Un denominador que contenga al numerador** (ganancia bruta, no P&L neto): el
   cociente vive en `[0, 1]` y no puede explotar. Es la mejor opción porque no
   tiene parámetro que calibrar.
2. **Si no, un piso explícito sobre `|denominador|`**, atado a la escala natural
   de lo que se divide y no a un número redondo.
3. **Debajo del piso va la diferencia absoluta con su unidad, y el informe dice
   por qué** no está el porcentaje.

Y la consecuencia: un cociente cuyo valor normal depende del tamaño de la muestra
se compara contra **su propia normal para ese n** (`5 mejores vs. lo normal`), no
contra un umbral fijo.

Los pisos viven en
[`tradingbot/backtest/cocientes.py`](tradingbot/backtest/cocientes.py), con de
dónde sale cada uno, y la auditoría de todos los cocientes que el informe publica
hoy está en [`ESTADO.md`](ESTADO.md), sección 10.

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

## El trailing chandelier — qué hace y qué NO se puede concluir de él

El stop sigue al **máximo alcanzado desde la entrada**, a `multiple × ATR` por
debajo, y no se activa hasta que el trade avanzó `activate_after_r`:

```yaml
exits:
  hard_stop:   {mode: atr, multiple: 2.0, atr_period: 14}
  trailing_stop:
    mode:             chandelier
    multiple:         3.0
    atr_period:       14
    activate_after_r: 1.0   # no se mueve nada hasta que el trade va +1R
```

Tres cosas del funcionamiento que conviene saber antes de leer un informe:

- **El nivel se recalcula al cierre de cada vela y rige desde la siguiente.**
  Mover el stop con el máximo de la vela `t` y después compararlo contra el mínimo
  de esa misma vela `t` sería mirar adentro de la barra. El precio de hacerlo bien
  es que el trailing llega un día tarde, y es el mismo precio que paga toda la
  ejecución del motor.
- **El stop nunca baja.** El único camino para moverlo es `raise_stop`, que
  rechaza cualquier nivel peor que el vigente. Importa porque el chandelier *sí*
  propone bajar cuando el ATR se agranda, que es justo cuando el trade se está
  dando vuelta.
- **La salida lleva su propio motivo.** `trailing_stop` cuando el mínimo lo toca y
  `gap_trailing_stop` cuando la vela abre por debajo (con fill en la apertura,
  igual que el hard stop). Sin esa distinción la atribución le cargaría al hard
  stop salidas que decidió el trailing, y la pregunta "¿qué regla me saca?"
  quedaría sin respuesta.

**Y lo que no se puede concluir.** El trailing entra **por decisión de diseño del
PLAN** —"las plantillas arrancan con dos capas prendidas, hard stop + trailing"—
y no porque se haya medido que aporta. El banco A/B, corrido entre las dos
plantillas sobre el fixture, da un empate:

```
tradingbot comparar -b config/strategies/ema_cross_sin_trailing.yaml                     -v config/strategies/ema_cross.yaml                     -d tests/fixtures/synthetic

  trades afectados  17 de 30 pares   ->  f = 0.567
  expectancy        +0.251R -> +0.036R
  delta pareado     -0.215 [-0.612, +0.152] p=0.282 n=30
```

Ese intervalo contiene el cero con holgura por los dos lados, y era esperable: el
mínimo detectable con f = 0.57 y 30 trades es ~0.98R por trade afectado. **La
corrida no tiene poder para distinguir −0.2R de 0**, así que el signo negativo del
punto estimado no es evidencia de nada. Y aunque lo tuviera, seguiría sin decir
nada sobre el trailing como regla, porque son series sintéticas
([`ESTADO.md`](ESTADO.md), sección 2).

Por eso el informe imprime el aviso donde el trailing aparece —en la tabla de
atribución, en el bloque de poder y en la lista de advertencias— y la CLI aclara,
abajo del veredicto del banco, que un empate **no** apaga una capa que no compite.

## Riesgo de cartera — los cinco controles

Un trader con veinte años no piensa en "este trade": piensa en cuánto tiene
expuesto en total y cuándo tiene que dejar de operar.

```yaml
risk:
  position_sizing:    {mode: risk_pct, risk_pct: 1.0, on: current_equity}
  max_position_pct:   30       # concentración, por trade
  max_open_positions: 10

  max_portfolio_heat_r: 4.0            # 4% del equity en riesgo abierto
  max_per_group:        {sector: 2}    # etiquetas de config/universe.yaml
  circuit_breaker:
    monthly_drawdown_pct: 6.0          # el mes va -6%: se deja de abrir
    peak_drawdown_pct:    15.0         # -15% del máximo: se cierra todo y se para
```

**No son candidatos del torneo, son restricciones**: no se miden con el banco A/B
ni se les calcula poder, se cumplen o no se cumplen. Por eso avanzaron sin esperar
datos reales.

- **El heat va en pesos.** `Σ(acciones × distancia al stop) / equity`, y `4.0` se
  lee como *4% del equity en riesgo abierto*, no como cuatro posiciones de 1R
  nominal (que en la práctica son ~3.1R). Una posición cuyo stop ya pasó arriba
  de la entrada aporta **cero**, no negativo. Detalle y motivos en
  [`ESTADO.md`](ESTADO.md), sección 5.
- **El límite por grupo lee las etiquetas de `config/universe.yaml`**, no del YAML
  de estrategia: el sector es del papel, no de la estrategia. Un símbolo del
  universo sin la etiqueta que pide `max_per_group` **hace fallar el backtest al
  arrancar**, en vez de caer en un cajón "otros" que sería un grupo más con su
  propio cupo.
- **Los dos cortacircuitos se evalúan antes de mirar las entradas de esa misma
  vela.** Si se evaluaran después del cierre, el freno regiría recién al día
  siguiente y esa noche saldría una orden más.

### Los rechazos se cuentan y se publican

El PLAN pide que el backtest refleje **las señales que realmente habrías podido
tomar**, no todas las que aparecieron. El informe trae la tabla:

```
tradingbot backtest -s config/strategies/cartera_correlacionada.yaml                     -d tests/fixtures/correlated

Señales rechazadas: 17
Categoría                 Señales     %   Qué la produjo
heat de cartera                 4   24%   el riesgo abierto más el de la señal pasaba max_portfolio_heat_r
límite por grupo               10   59%   ya había max_per_group posiciones del mismo grupo
cash                            3   18%   no alcanzaba la plata para comprar ni una acción
```

y debajo el detalle con nombre y apellido
(`límite por grupo sector=energy: ya hay 2 (COP, CVX) y el tope es 2`). Un
backtest que descarta señales en silencio miente en la dirección optimista dos
veces: no muestra lo que el riesgo de cartera frenó, y hace parecer que el sistema
opera más de lo que puede.

El informe publica además el **heat realizado** (máximo, medio y días con
posición) contra el tope configurado. El máximo puede quedar unas décimas por
encima del tope y no es un bug: el control es *ex ante* —se aplica contra la
equity del cierre de la señal— y si después la equity cae, el mismo riesgo abierto
pesa más. El informe lo explica cuando pasa.

**Que el heat máximo quede pegado al tope sin pasarlo (3.93% contra 4.00%) es
mérito del control y no del fixture**, y eso está medido y no supuesto: sin
ningún control de cartera el mismo universo llega a **5.03%**, pasa el 4% en 79
de los 890 días con posición y llega a tener **7 posiciones abiertas a la vez**.
Los rechazos por heat son pocos en esa plantilla porque `max_per_group: 2` se
evalúa antes y absorbe la mayor parte de la presión; con el heat como único
control y el mismo tope, los rechazos son 20. El control se prueba además con
topes de 3%, 2% y 1%, donde rechaza 54, 75 y 94 señales y el invariante se
mantiene igual. Los números y el razonamiento están en
[`ESTADO.md`](ESTADO.md), sección 5.

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
| `ema_cross.yaml` | Cruce de medias con filtro de tendencia. La del plan. Línea base: hard stop + trailing + objetivo. |
| `ema_cross_sin_trailing.yaml` | La misma con el trailing apagado. **No es otra estrategia**: es el par de comparación del banco A/B y la que usan las mediciones de sizing, que son del lado de la entrada. |
| `cartera_correlacionada.yaml` | Las mismas reglas sobre los 10 símbolos del universo correlacionado, con los cinco controles de riesgo de cartera prendidos. Existe para que la tabla de rechazos tenga algo que mostrar: con los 4 símbolos de `ema_cross` en dos sectores de a dos, `max_per_group: 2` no se puede violar nunca. |
| `rsi_pullback.yaml` | Retroceso sobre tendencia alcista. La del plan. |
| `breakout_52w.yaml` | **Pendiente.** Ruptura del máximo de 52 semanas: necesita el indicador `donchian`, que llega en la tanda 2. El slot queda vacío a propósito. |
| `extra_bollinger_upper_break.yaml` | Extra, no está en el plan. Ruptura de la banda superior de Bollinger. **No reemplaza a `breakout_52w`**: el máximo móvil es momentum y Bollinger es reversión a la media. |

Lo que todavía no existe se **rechaza con un mensaje que lo dice**: poner
`break_even:` hoy no se ignora en silencio, falla explicando que es del torneo de
la 2C. Y los modos de trailing que el plan nombra pero que no están (`pct`,
`structure`, `psar`) se rechazan igual, aunque el bloque `trailing_stop` sí
exista. Un backtest que ignora en silencio la mitad de tu configuración miente.

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

**Cuántos skips esperar.** Seis son fijos en un entorno sin red y sin los CSV
reales: cuatro `@pytest.mark.network` y dos que necesitan `SPY.csv` / `AAPL.csv`.
Los cuatro del navegador se suman o no según lo que haya:

| Situación | Skips |
|---|---|
| Con Chromium (instalado o vía `TRADINGBOT_CHROMIUM`) | **6** |
| Sin Chromium, o con la variable apuntando a un binario que no existe | **10** |

Los cuatro del navegador saltan **limpio** en los tres casos —sin ruido de
teardown— porque la verificación ocurre antes de abrir Playwright: saltear ya
adentro del context manager deja excepciones de cierre que se leen como fallas.

## Estructura

```
tradingbot/
  config.py          carga YAML + valida con pydantic (errores claros, no KeyError)
  data/              provider ABC, yahoo, stooq, csv local, cache parquet, validación
  indicators/        trend, momentum, volatility + registry ("ema" -> función)
  strategy/          conditions, engine (all/any/not), risk (sizing), position,
                     exits (hard stop, trailing chandelier, objetivo),
                     portfolio_risk (heat, grupos, cortacircuitos)
  backtest/          engine (loop barra a barra), portfolio, costs, metrics,
                     manifest, ab (banco de comparación), poder (MDE por capa)
  reporting/         informe de consola y HTML mobile-first con gráficos Plotly
  cli.py             typer: backtest, comparar
```

Las capas no se saltean: `data -> indicadores -> reglas -> backtest -> salida`.
