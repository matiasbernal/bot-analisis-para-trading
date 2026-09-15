# Estado del proyecto

Este archivo es para alguien que llega sin haber estado en las conversaciones que
llevaron hasta acá. Cuenta **dónde está el proyecto, qué se decidió y por qué**.
Lo que el código hace está en el código; lo que hay acá son las razones, que es
lo único que no se puede reconstruir leyéndolo.

- El diseño original está en [`PLAN.md`](PLAN.md). Sigue siendo la referencia,
  con dos correcciones marcadas dentro del propio archivo (cómo se calcula el
  heat, y qué puede decir la alerta).
- Cómo usar la herramienta está en [`README.md`](README.md).
- **Rama canónica: `claude/trading-analysis-bot-8ehd5h`.** Es la única que tiene
  toda la historia del proyecto. Si estás leyendo esto desde otra rama, lo que
  corresponde es llevar los commits acá, no seguir ahí (ver la convención de rama
  en la sección 11: pasó dos veces).

---

## 1. Dónde está el proyecto

**Tanda 1 (Fases 0, 1 y 2) cerrada con el checklist del plan cumplido**: capa de
datos con cache y validación, siete indicadores con registry, motor de reglas por
YAML, y un motor de backtest propio con costos, métricas, benchmark y manifiesto
reproducible. Tres commits, uno por fase.

Después de cerrarla se hicieron dos rondas más de trabajo sobre el mismo motor,
todas a partir de huecos encontrados revisando el resultado contra el plan:

| Ronda | Qué salió de ahí |
|---|---|
| Bloques 1-8 + D | Métricas verificadas a mano · benchmark SPY como tercera columna · el cierre forzado por fin de datos sale de las estadísticas · warmup cubierto por tests · cotejo con `backtesting.py` con costos · **medición del riesgo real por trade** · rótulos honestos · aviso de rango recortado |
| Bloques 1-5 (unidad de riesgo) | `return_on_risk` y la unidad de riesgo real · aviso cuando `risk_pct` queda decorativo y tope a 30 · concentración calibrada · **universo sintético correlacionado** · consecuencias escritas para la Fase 4 |
| Cinco cierres | Universo correlacionado rearmado para poder probar `max_per_group` · el aviso del tope ejercitado en el régimen que lo motivó · duración del MDD verificada a mano · la racha con su contexto · registro de calibración |

**Estado de verificación al cerrar**: `273 passed, 6 skipped` en un venv nuevo con
Python 3.11. Los 6 skips son los cuatro tests que necesitan red y los dos que
necesitan los CSV reales, que todavía no existen.

**Qué sigue: Fase 3, loteada en tres.** La tensión que había acá —el plan ponía las
siete capas en una sola tanda y al mismo tiempo pedía medir cada una sola— quedó
resuelta el 2026-09-12 y **la decisión está escrita en `PLAN.md`**, en la sección
"El torneo de capas" y en la tabla de la Fase 3. Resumen, para no tener que ir:

- **2A**: estado de la posición abierta, el banco de comparación A/B con bootstrap
  pareado por trade, el poder de medición publicado **por capa**, y `trailing_stop`
  escrito. **Escrito, no prendido**: desde el 2026-09-13 el trailing es candidata
  del torneo de 2C y la línea base es hard stop + take profit (sección 12).
- **2B**: riesgo de cartera. Va en el medio y no al final porque cambia el tamaño
  de las posiciones, y el tamaño cambia toda expectancy en pesos: si el torneo
  corre primero, sus mediciones quedan obsoletas el día que entra el heat.
- **2C**: el torneo, de a una, en orden de grados de libertad creciente, con una
  pasada final donde las capas descartadas se reevalúan contra la configuración
  ganadora. **PARADO hasta que haya CSV reales**, por la razón de la sección 2:
  sobre series sintéticas el torneo mediría el generador y no el mercado, y eso
  no lo arregla generar más trades.
  **Y había una segunda razón, que el 2026-09-13 dejó de valer**: recalculado el
  poder con el trailing prendido como línea base, ninguna de las cuatro capas
  estimables quedaba medible ni siquiera a n=230. Eso fue lo que hizo caer la
  regla: el trailing pasó a ser candidata del torneo y la línea base es hard stop
  + take profit (sección 12 de acá; el cambio está en `PLAN.md`). Rehecha la
  proyección con la línea base nueva, **el torneo vuelve a decidir**: con 13 ETFs
  y n=315, dos capas pasan el corte de 1/3 con los dos fixtures de acuerdo
  (`trailing_stop` y `time_stop`) y tres con cada fixture por separado, contra
  **cero** con la línea base vieja. La tabla completa, con las tres opciones de
  universo, está en `PLAN.md`, "Cuántas capas decide cada universo".

  **El universo elegido es el de 13 ETFs**, y lo que lo decide no es solo el
  sesgo: sin trailing los trades duran 29 velas en vez de 17, así que el cupo de
  cinco posiciones simultáneas pone un techo de 662 trades en 15 años **haya 13
  símbolos o 40**. Ampliar a 33 compra una sola capa (`market_regime`, y entra
  por 1.3 puntos en una tabla que discrepa por factores de dos entre fixtures) y
  ampliar a 40 no compra ninguna. El sesgo de supervivencia de las 20 acciones se
  pagaría por nada.

  **El n=315 de este párrafo era proyección sobre sintéticos.** Medido sobre los
  13 ETFs reales (con el cash ya corregido, sección de arriba) el ritmo real es
  1.30 t/símbolo-año, no 1.75, y da 249 trades (155 in-sample), no 315. La
  conclusión de universo no cambia; los números si se quiere planear el torneo
  con ellos, sí. Corrección completa, con la palanca que de verdad ata (el cash,
  no `max_open_positions`), en `PLAN.md`, "El ritmo real y la palanca, medidos".

**Estado al cerrar esta tanda (2A + 2B).** 2A completa: `position.py` con sus
tres invariantes, el banco A/B, el poder por capa, y el trailing chandelier
—que entra por diseño, no validado—. 2B completa: `portfolio_risk.py` con los
cinco controles, el heat en pesos y los rechazos registrados con motivo. Lo que
queda pendiente es 2C, y lo que le falta no es código.

Las dos decisiones de fondo que conviene no re-discutir sin leer el fundamento:
cada capa se decide con walk-forward **dentro del in-sample** y el out-of-sample
se gasta una sola vez al final del torneo (seis decisiones contra el OOS lo gastan
seis veces: ~26% de probabilidad de quedarse con al menos una capa inútil), y el
resultado del torneo **depende del orden**, así que el orden se registra con el
resultado.

---

## 2. Los fixtures sintéticos: para qué sirven y para qué no

Esta es la distinción más fácil de perder y la más cara: **hay dos usos posibles
de un fixture y el repo solo soporta uno**. Está escrito acá porque en dos meses
un `pytest` en verde sobre datos sintéticos se va a leer como validación de la
estrategia, y no lo es.

| | Verificar el MOTOR | Decidir si una capa APORTA |
|---|---|---|
| La pregunta | ¿el código hace lo que dice? | ¿esta regla gana plata? |
| Ejemplos | el trailing nunca baja el stop · el gap llena en la apertura y no en el precio del stop · el heat rechaza la sexta señal · la atribución de salidas suma el total de trades · `max_per_group` deja una señal afuera | el trailing mejora la expectancy · `giveback` aporta sobre el trailing ya fijo · el filtro de régimen paga lo que cuesta |
| ¿Sirven los sintéticos? | **Sí, y son mejores que datos reales**: la serie es determinística y las velas a mano no tienen ambigüedad | **No, y el resultado no es "débil" sino que no significa nada** |

### El fixture estresado de gaps: prueba mecánica, no realismo

Hay un tercer fixture que no entra en la tabla de arriba sin una aclaración, y la
aclaración es la misma que la de la fila derecha: **este fixture prueba mecánica,
no realismo.**

`test_gaps_correlacionados_saltan_varios_stops_la_misma_manana` no usa el
universo correlacionado por defecto sino una versión **estresada**:
`gap_volatility=0.05` (16× la de por defecto) y stops de `0.75×ATR` en vez de
`2.0×ATR`. Y esos dos parámetros **se eligieron contra el resultado deseado**: se
subieron hasta que el fixture produjera 5 mañanas con 2 o más stops saltando
juntos, porque con los parámetros normales casi ningún gap llega al stop y no
había escenario que probar.

Eso es legítimo **para la pregunta que el test hace**, que es de motor: *¿el heat
se recalcula bien después de varios stops simultáneos?* La guardia no lleva
contador incremental justamente para sobrevivir esa mañana, y sin la mañana el
invariante no se ejercita nunca. El test verifica el heat contra una
reconstrucción independiente en cada una de esas fechas, y eso es verdadero o
falso con total independencia de si los gaps son realistas.

Lo que el fixture **no** puede sostener es ninguna afirmación sobre frecuencias:
no dice cada cuánto pasa una mañana así, ni con qué probabilidad, ni cuánto
riesgo de gap tiene una cartera de verdad. Un parámetro calibrado hasta que
aparezca el escenario que uno quiere ver no mide con qué frecuencia aparece el
escenario. Si algún día alguien quiere ese número, sale de datos reales y de
ningún otro lado.

**Por qué el segundo uso no se arregla con más datos sintéticos.** No es un
problema de muestra chica. Las capas de salida explotan estructura del precio —
retrocesos, persistencia, cuánto dura un movimiento antes de darse vuelta— y en
estas series esa estructura **la define el generador**: `_ohlcv_from_shocks` arma
cada vela con shocks normales iid sobre el cierre, un gap independiente en la
apertura y un rango intrabar sorteado aparte. Un random walk no tiene retrocesos
con memoria, ni volatilidad agrupada, ni colas gordas. Un torneo corrido ahí no
mediría el mercado: mediría `_ohlcv_from_shocks`. Con 300 trades sintéticos el
intervalo de confianza se angosta alrededor del número equivocado, que es peor
que un intervalo ancho, porque parece una respuesta.

Ninguna de las dos propiedades que el generador **sí** reproduce a pedido cambia
esto. La correlación entre símbolos (`correlated_universe`) es real y es lo que
hace medibles los controles de cartera —el heat, `max_per_group`, los gaps
simultáneos—, pero eso son **restricciones**, no candidatas de torneo: se cumplen
o no, y eso se verifica. Y el drift positivo hace que un backtest dé coherente,
que es un test de cordura del motor, no evidencia sobre una regla.

**La consecuencia práctica**, para no tener que volver a razonarlo:

- Un test que fija un número medido sobre sintéticos (una correlación, una
  fracción, un umbral) es legítimo: fija el **comportamiento del código**, para
  que se note si cambia.
- Un test que dijera "con el trailing la expectancy sube 0.2R, así que el
  trailing aporta" sería ilegítimo, aunque estuviera en verde. **No hay ninguno
  y no tiene que haberlo.**
- Por eso `trailing_stop` se **escribió** en 2A sin estar validado, y el informe
  lo dice donde aparece el trailing. Hasta el 2026-09-13 además entraba
  *prendido*, por decisión de diseño del PLAN; desde esa fecha es candidata del
  torneo como cualquier otra capa (sección 12). Lo que no cambió es esto: sobre
  series sintéticas su aporte no se puede decidir ni con más trades.
- Y por eso 2C —el torneo— **está parado hasta que haya CSV reales**, aunque el
  banco A/B y el módulo de poder ya funcionen. El instrumento está listo; lo que
  falta no es instrumento, es mercado.

## 3. Por qué `max_position_pct` es 30 y no 20

El tamaño de cada posición sale del menor de tres números: el que pide el riesgo,
el que permite el tope de concentración y el que alcanza el cash. Igualando los
dos primeros sale una relación aritmética que no estaba en el plan y que decide
todo:

> **el tope de concentración decide el tamaño cuando la distancia al stop, en %
> del precio, es menor que `risk_pct / max_position_pct`.**

Con `risk_pct: 1.0` y `max_position_pct: 20` ese umbral es **5%**. Un stop de
2×ATR sobre estos papeles está a ~4.4% del precio. Resultado medido sobre la
plantilla `ema_cross` y el fixture: **el tope decidía el tamaño en 21 de 31
trades**, y `risk_pct` no decidía nada. El riesgo realizado promedio caía a
**0.78R** (mínimo 0.54R).

Con `max_position_pct: 30` el umbral baja a 3.33%, queda por debajo de la
distancia típica al stop, y el riesgo vuelve a 0.95R de media (mínimo 0.83R) con
el tope atando **1 de 31**.

**Lo importante no es el 30.** 20% no es malo en sí: es malo *en relación* a
`risk_pct: 1.0` y stops de 2×ATR. Con tope 30 y `risk_pct: 1.5` vuelve el mismo
problema, porque 1.5/30 es otra vez 5%. Por eso lo que se construyó no fue
"subir el número" sino **el aviso**:

- `config.py` calcula `sizing_threshold_pct` y, cuando el stop es porcentual (la
  distancia se conoce sin mirar datos), avisa al validar;
- con stops en ATR la distancia no se conoce hasta tener los datos, así que el
  aviso lo emite el motor al arrancar el backtest, comparando el umbral contra la
  distancia mediana al stop;
- y el informe imprime **quién decidió el tamaño** en cada corrida:
  `Quién decidió el tamaño   riesgo 30, tope 1, cash 0 (de 31 señales)`.

Es aviso y no error: hay configuraciones donde que el tope mande es intencional.
`tests/test_riesgo_realizado.py` fija el comportamiento en los dos regímenes, así
que si alguien rompe el aviso, se entera.

---

## 4. El sesgo ATR: dormido, no resuelto

El tope ata cuando el stop está cerca, y el stop está cerca cuando el ATR es
bajo. O sea que **el motor arriesga menos en los trades tranquilos y 1R completo
en los volátiles**, que es exactamente al revés de lo deseable. Medido:

| `max_position_pct` | correlación riesgo ↔ distancia al stop | tercio de stops cercanos | tercio de lejanos |
|---|---|---|---|
| 20% | +0.92 | 0.596R | 0.938R |
| 30% | +0.06 | 0.941R | 0.943R |

Con el tope en 30% el sesgo **está dormido, no resuelto**. Lo despierta cualquier
cosa que vuelva a hacer atar el tope:

- una cuenta más chica (el redondeo a acciones enteras pesa más),
- papeles más caros en relación al capital,
- stops más ajustados (menos ATR de multiplicador),
- un `risk_pct` más alto sin tocar el tope.

`test_el_sesgo_por_atr_aparece_cuando_el_tope_ata` fija las dos mediciones para
que se note si reaparece. No hay solución implementada: ninguna de las tres
opciones evaluadas (redimensionar en el fill, subir el capital, aceptar y
reportar) lo elimina; lo que se hizo fue sacarlo del camino y dejarlo medido.

---

## 5. La unidad de riesgo: `return_on_risk` y el heat

**1R no vale lo que dice el YAML.** `risk_pct: 1.0` sobre $10.000 declara $100 por
trade, pero el riesgo realizado es `acciones × riesgo por acción`, y eso es menos:
el tamaño se redondea a acciones enteras y el tope recorta posiciones. Cada
`Trade` guarda las dos cosas: `risk_amount` (realizado) y `risk_target` (declarado
al momento de la señal).

**La expectancy del plan no se tocó**: sigue siendo la media de `pnl_r`, "cuánto
deja un trade típico", con cada trade pesando igual. Es lo correcto para juzgar
una regla y es como se usa mentalmente.

**`return_on_risk` (Σpnl / Σriesgo real) es otra métrica y va al lado, no en
lugar.** Pondera cada trade por la plata que puso en juego, así que responde otra
pregunta: cuánto devolvió cada peso arriesgado. Con R constante entre trades las
dos coinciden; cuanto más dispersa es la R realizada, más se separan.

El problema concreto que esto resuelve: traducir la expectancy a plata
multiplicando por el 1R declarado. Con el tope en 20% esa cuenta daba $25.09 por
trade cuando el promedio real era $17.27 — **45% de más**. Por eso el informe
imprime juntas la expectancy en R, la expectancy en plata y el 1R realizado
promedio, y avisa cuando la lectura ingenua se desvía.

**Consecuencia para la Fase 3, que es la razón de todo esto**: el heat de cartera
se calcula en pesos, no contando R nominales.

```
heat = Σ(riesgo real de las posiciones abiertas) / equity
```

`max_portfolio_heat_r: 4.0` se lee como **4% del equity en riesgo abierto**.
Contar "cuatro posiciones de 1R" daría 4R nominales que en la práctica eran
~3.1R, y el cortacircuito quedaría calibrado sobre una unidad que no es la que
dice. Lo mismo vale para cualquier lectura tipo "cinco pérdidas seguidas son
−5R": por eso el informe publica el costo de la peor racha **en plata**.

### Cómo quedó implementado, al hacer la 2B

Cinco decisiones que el plan no fijaba y que conviene no re-discutir a ciegas.
Todas están en `strategy/portfolio_risk.py` con su motivo al lado del código:

- **El ancla del riesgo es el precio de entrada, no el cierre de hoy.** El
  riesgo de una posición abierta es `acciones × (entrada − stop)`, que es la
  fórmula del PLAN. La alternativa —`(cierre de hoy − stop)`— también es
  defendible, pero haría que el heat subiera solo porque el precio subió, sin
  que nadie hubiera tomado más riesgo, y `max_portfolio_heat_r` dejaría de
  significar lo mismo el día 1 que el día 20.
- **Se suma la parte positiva de cada posición, no la suma con signo.** Una
  posición con el stop arriba de la entrada (trailing ya armado, o el break-even
  de la 2C) aporta **cero**, no negativo. Aportar negativo dejaría que dos
  trades cubiertos "paguen" la apertura de un tercero expuesto.
- **Las órdenes pendientes cuentan.** Si no contaran, cinco señales de la misma
  noche pasarían las cinco —ninguna ve a las otras— y el heat se enteraría al día
  siguiente, con las cinco adentro.
- **El control es EX ANTE.** Se aplica cuando llega la señal, contra la equity de
  ese cierre. Si después la equity cae, el mismo riesgo abierto pesa más y el heat
  realizado puede quedar unas décimas arriba del tope: medido sobre el universo
  correlacionado, 4.09% contra un tope de 4.00%. **No es un incumplimiento**;
  bajarlo pediría recortar posiciones ya abiertas, que es otra decisión y no está
  en el plan. El informe lo explica cuando pasa.
- **El heat no se lleva en un contador.** Se recalcula desde las posiciones vivas
  en cada consulta. Un acumulador incremental se desincroniza el día que varios
  stops saltan la misma mañana —justo el escenario para el que existe el
  control— y el error no se ve, porque el número sigue siendo plausible. Hay un
  test que compara el heat del motor contra una reconstrucción independiente en
  **todas** las velas del período: coinciden a 1e-17.

### ¿El heat está apenas activo? Medido, no supuesto

El informe de `cartera_correlacionada` publica **heat máximo 3.93% contra un tope
de 4.00%**: el 98% del tope sin pasarlo, con pocos rechazos. Eso admite dos
lecturas opuestas —que el control frenó justo a tiempo, o que las señales
simultáneas son tan raras acá que el 4% nunca estuvo realmente en juego— y la
segunda haría que el número no probara nada. Así que se midió.

**La demanda existe y sobra.** Sobre el mismo universo correlacionado y **sin
ningún control de cartera prendido**:

| | |
|---|---|
| heat máximo | **5.03%** (25% arriba del tope) |
| días con heat > 4% | **79** de 890 días con posición (8.9%) |
| días con heat > 3% | 329 (37%) |
| posiciones simultáneas | hasta **7** |

O sea que el 3.93% es mérito del control y no del fixture. `test_el_fixture_
genera_demanda_de_heat_muy_por_encima_del_tope` fija las tres cosas, para que si
algún día el fixture deja de producir el escenario, se entere el que lo cambió y
no el que lea el informe.

**Por qué entonces solo 4 rechazos por heat.** Porque en esa plantilla el heat no
trabaja solo: `max_per_group: 2` se evalúa antes y absorbe la mayor parte de la
presión (saca posiciones del mismo sector, que son justo las que apilan riesgo
correlacionado). Sacándole el límite por grupo a la misma plantilla, los rechazos
por heat suben de 3 a 8 y los trades de 96 a 108, con el heat máximo clavado en
3.93% en los dos casos. Y con el heat como **único** control sobre el universo
correlacionado, al mismo tope de 4%, los rechazos son **20**. El control estaba
atando; lo que era chico era su turno, no su fuerza.

**Y la confianza no queda apoyada en ese 98%.** Un test parametrizado corre el
mismo control con topes de 3%, 2% y 1%:

| tope | trades | rechazos por heat | heat realizado máx. |
|---|---|---|---|
| sin tope | 106 | — | 5.03% |
| 4.0% | 92 | 20 | 4.09% |
| 3.0% | 68 | 54 | 3.00% |
| 2.0% | 47 | 75 | 2.01% |
| 1.0% | 28 | 94 | 1.00% |

En los cuatro se mantiene el invariante que importa: **el heat realizado nunca se
va más de medio punto arriba del tope**, y ese margen es el desborde *ex ante* ya
documentado arriba (el control se aplica contra la equity del cierre de la señal;
si después la equity cae, el mismo riesgo abierto pesa más). Tres órdenes de
exigencia distintos y la misma aritmética: si el 3.93% fuera casualidad del
fixture, acá se rompería.

Y dos decisiones sobre los cortacircuitos:

- **El mensual es un latch dentro del mes**: una vez que saltó no se levanta
  porque la equity repunte, solo al cambiar el mes. La regla es dejar de operar el
  mes malo, no operar en los repuntes del mes malo.
- **El del pico no se reanuda solo.** −15% desde el máximo no es una racha, es la
  sospecha de que el método o el mercado cambiaron; reanudar automáticamente lo
  convertiría en una pausa. En el backtest eso significa que no se abre nada más
  en lo que queda del período, y el informe lo registra con su motivo.
- Los dos se evalúan **antes** de mirar las entradas de esa misma vela, no después
  de la marca: si se evaluaran después, el freno regiría recién al día siguiente y
  esta noche saldría una orden más.

---

## 6. El formato de alerta decidido (Fase 4, sin implementar)

El plan define una alerta que imprime `Riesgo: 1.0R = $101`. Con la unidad real
hay que reescribirlo, y hay un dato que cambia el diseño: **el riesgo en pesos sí
se conoce la noche anterior**. La cantidad de acciones y el riesgo por acción se
fijan al cierre de la señal, así que `acciones × riesgo por acción` es exacto
antes de mandar la orden. Lo que **no** se conoce es el precio del stop, porque se
ancla al fill de la apertura.

```
🟢 ENTRADA · MSFT
Mañana en apertura (orden MOO)

Comprar: 13 acciones
Riesgo:  $98.21  (0.98R de $100 declarado)
Stop:    apertura − $7.55 por acción
         ≈ $142.04 si abre como cerró
Target:  apertura + $22.66  (3R)
```

Las tres reglas, con su razón:

- **El riesgo en pesos va exacto, sin "~"**, porque lo es. Al lado, cuánto es
  contra el 1R declarado: ahí se ve si el tope recortó la posición.
- **Stop y objetivo van como distancia por acción, no como precio.** El precio
  exacto depende de la apertura; darlo redondo invita a cargar una orden de stop
  al número equivocado. El precio estimado va abajo, **marcado como estimación**.
- **Única excepción al "exacto"**: si el cash no alcanza al momento del fill, el
  motor recorta acciones. La alerta lo aclara cuando la posición usa más del 90%
  del cash disponible.

---

## 7. El universo correlacionado y para qué está cada grupo

Hay **dos** universos sintéticos y la diferencia importa:

- `tests/fixtures/synthetic/` — 4 series **independientes** (ρ ≈ −0.01). Es el de
  la tanda 1 y sus números están fijados en los tests. No se toca.
- `tests/fixtures/correlated/` — 10 series **correlacionadas por grupos**. Es el
  que hay que usar para cualquier cosa que dependa de cómo se mueven juntas.

Por qué hacen falta los dos: sobre las series independientes la volatilidad de la
cartera es el **32%** de la de sus componentes (pura diversificación de ruido),
contra **78%** en el correlacionado, y el drawdown de la cartera correlacionada es
**2.2×** el de la misma cartera sin correlación. Todo control de riesgo de cartera
probado sobre las primeras se vería mucho mejor de lo que es.

```
  mercado    1  SPY                        ρ 0.70 contra todo lo demás
  tech       4  AAPL, MSFT, NVDA, QQQ      ρ 0.85 adentro del grupo
  energia    3  XOM, CVX, COP              ρ 0.85 adentro del grupo
  defensivo  2  JNJ, PG                    ρ 0.35 entre grupos distintos
```

Cada decisión de esa estructura tiene un motivo:

- **ρ alta adentro y baja entre grupos**, en vez de una ρ uniforme: con una sola
  ρ para todos los pares, `max_per_group` no se puede distinguir de
  `max_portfolio_heat_r`, porque todas las posiciones serían igual de
  redundantes entre sí. El límite por sector necesita que el sector signifique
  algo.
- **Un grupo de 4 y otro de 3**, no dos por grupo: con dos símbolos por sector,
  `max_per_group: 2` **no se puede violar nunca** y el control quedaría sin test.
  Medido sobre un cruce de medias corriente y sin límite por grupo, el fixture
  produce 166 días-grupo con 3+ posiciones abiertas del mismo sector y 32 con 4+.
- **SPY aparte, correlacionado con todo a 0.70**: es el índice, y además el
  benchmark de mercado que la regla de rigor 5 exige en todo informe.
- **`gap_corr` controlable aparte**: los gaps de apertura correlacionados son lo
  que decide si varios stops saltan la misma mañana, que es el escenario que el
  heat tiene que sobrevivir. Con la estructura por defecto hay 52 mañanas con 4+
  símbolos abriendo −0.5% o peor; con `gap_corr=0.0`, dos.

El generador (`tests/fixtures/synthetic.py`) mezcla normales independientes con
el factor de Cholesky de la matriz pedida, así que la correlación es la pedida
salvo error muestral, y cada símbolo mantiene su drift y su volatilidad. Una
matriz imposible falla con un mensaje que lo dice.

---

## 8. Qué está deliberadamente afuera, y por qué

**Redimensionar en el fill (la opción "B1").** Recalcular las acciones con
`open[t+1]` ya conocido en vez de estimar con `close[t]`. Se evaluó con números y
se **descartó**:

- sobre la estrategia real no cambia nada (0 de 31 trades cambian de tamaño con
  $10.000 y tope 20): el problema del riesgo no venía de ahí;
- sí cerraría el residuo del cotejo con `backtesting.py` (las acciones pasan a
  coincidir 100%), pero ese residuo ya está explicado y documentado;
- y tiene un costo operativo real: perderías el tamaño conocido al mandar la
  orden market-on-open, que es justo la operativa de cargar la orden a la noche.

**Subir el `initial_cash` de las plantillas (la opción "B2").** Descartada: con el
tope en 20% ningún capital arregla el problema (la media converge a 0.85 y no
sube más), así que sola no arregla nada, y combinada con el tope al 30% el que
arregla es el tope.

**`breakout_52w.yaml`.** El plan la lista como plantilla; necesita un indicador de
máximo móvil (`donchian`) que no está en la tanda 1. **El slot queda vacío a
propósito**, anotado en la tabla de plantillas del README. Existe
`extra_bollinger_upper_break.yaml`, que es una plantilla extra y **no la
reemplaza**: el máximo de 52 semanas es ruptura de momentum y Bollinger es
reversión a la media, o sea otra familia de estrategia.

**La máscara de warmup sobre `exit_signal` ya está hecha**, no es un pendiente.
Se aplicó aunque hoy sea inocuo (no se puede salir de una posición que no se pudo
abrir) porque cuando la Fase 3 agregue capas que leen indicadores al cierre nadie
se va a acordar.

**La red.** El sandbox donde se construyó esto **no llega a Yahoo ni a Stooq**: el
proxy del entorno rechaza el CONNECT con 403. Todo se probó sobre fixtures. Los
cuatro tests marcados `@pytest.mark.network` detectan conectividad haciendo un GET
real (no alcanza con abrir el socket: el proxy acepta la conexión y rechaza
después) y se saltean con el motivo; se prenden solos en una sesión donde la
política de red permita esos hosts. Los CSV reales (`SPY.csv`, `AAPL.csv`) los
genera el usuario en su máquina con `scripts/fetch_fixture.py`; hasta entonces los
dos tests que los usan se saltean.

---

## 9. Qué números del informe cambiaron, calibración por calibración

La plantilla `ema_cross` declara su calibración en el YAML y el informe la imprime
en el encabezado, justamente para que dos informes de la misma estrategia no se
confundan. **v1 = `max_position_pct: 20`; v2 = `30`; v3 = v2 + trailing
chandelier.** Sobre el mismo fixture:

| | v1 (tope 20) | v2 (tope 30) | v3 (+ trailing) |
|---|---|---|---|
| Equity final | $10.486 | $10.681 | $9.966 |
| CAGR | 1.00% | 1.39% | −0.07% |
| Max drawdown | −4.96% | −5.51% | −5.82% |
| Duración de ese DD | 957 d | 371 d | 556 d |
| DD más largo | 957 d | 385 d | 556 d |
| In-sample CAGR | −0.17% | +0.18% | −1.30% |
| Out-of-sample CAGR | 2.82% | 3.26% | +1.82% |
| Expectancy | +0.25R | +0.25R | +0.04R |
| Expectancy en plata | $+17.27 | $+24.51 | $+0.67 |
| 1R realizado promedio | $78.53 | $95.89 | $91.41 |
| Error de la lectura ingenua | 45% | 3% | — (la expectancy en plata es ~0) |
| Días con posición | — | 47.68% | 28.00% |

**Sobre la columna v3 hay que ser muy claro: NO dice que el trailing sea malo.**
Dice tres cosas y ninguna es esa:

1. El banco A/B, corrido entre las dos plantillas, da un **empate**:
   `delta pareado −0.215R [−0.612, +0.152] p=0.282`, con f = 0.567 (17 de 30
   trades cambiados). El intervalo contiene el cero con holgura por los dos lados.
2. Ese empate es lo que había que esperar: el MDE con f = 0.57 y 30 trades es de
   ~0.98R por trade afectado, y el efecto observado es 0.38R. **La corrida no
   tiene poder para distinguir −0.2R de 0.** Que el punto estimado sea negativo
   no es evidencia de nada.
3. Y aunque tuviera poder, seguiría sin decir nada sobre el trailing **como
   regla**, porque estas son series sintéticas: un chandelier explota
   retrocesos y persistencia, y en un random walk esa estructura la define el
   generador (sección 2).

Por eso el trailing entra igual, por decisión de diseño del PLAN, y por eso el
informe imprime el aviso donde aparece. La bajada de "días con posición" de 47.68%
a 28.00% sí es un hecho del motor y no una opinión: el trailing corta los trades
antes, y eso libera capital, que es lo que la 2B pasa a administrar.

Un dato lateral que vale la pena: el σ del efecto **medido por el banco** dio
1.44R contra el 1.43R que `poder.py` estimaba a priori con `FACTOR_SIGMA`. La
calibración de la 2A resultó buena; sigue siendo una calibración.

De v1 a v2 todo es consecuencia del mismo cambio: posiciones más grandes ganan y
pierden más. El drawdown más profundo empeora (−4.96% → −5.51%) y a la vez dura
mucho menos, y eso tiene una explicación verificada a mano: **no es el mismo
drawdown más corto, es un episodio largo que se parte en dos** porque la equity
ahora sí recupera su máximo en el medio.

```
v1: pico 2018-11-02 ($10.071,07) → valle 2020-07-14 ($9.571,29) → recupera 2021-06-16   = 957 d
v2: pico 2018-11-02 ($10.071,07) → valle 2019-02-27 ($9.604,94) → recupera 2019-11-22   = 385 d
    (y arranca otro: pico 2020-01-14 → valle 2020-07-14 (−5,51%) → recupera 2021-01-19  = 371 d)
```

Dos cambios más del informe que no vienen del tope:

- **El cierre forzado por fin de datos salió de las estadísticas de trades.** No
  lo decidió ninguna regla y es el único fill que ejecuta al cierre en vez de en
  la apertura siguiente. Se reporta aparte ("Posiciones abiertas al cierre del
  período") y su plata sigue contando en la equity y en los costos. Por eso
  "Trades" dice 30 y no 31.
- **La concentración cambió de fórmula y de lectura.** Antes dividía por el P&L
  neto y daba 252,77%, un número que no se puede interpretar y que explota si el
  neto es negativo. Ahora el denominador es la ganancia bruta y lo que se muestra
  es el cociente contra lo normal para esa cantidad de ganadores
  (`5 mejores vs. lo normal: 0.78×`). El umbral fijo de 80% no estaba calibrado
  sobre nada: saltaba en el 100% de los casos sanos con 6 ganadores y en el 0%
  con 20.

---

## 10. La regla del cociente inestable

Tres veces apareció el mismo error con tres caras distintas, y las tres se
arreglaron por separado antes de que alguien notara que era el mismo error:

| Dónde | Qué se publicaba | Qué pasaba |
|---|---|---|
| concentración del resultado | **252%** | dividía por el P&L **neto**, que es la resta de dos números grandes y puede quedar en cualquier cosa, o negativo |
| error de la lectura ingenua | **426%** | dividía por la expectancy en plata, que con una estrategia empatada vale $0.67 |
| cotejo contra `backtesting.py` | **118%** de diferencia de CAGR en MSFT | dividía por un CAGR de 30 puntos básicos: la diferencia absoluta era media décima de punto |

En los tres el numerador estaba bien medido. El problema es que **un cociente
hereda la estabilidad de su denominador**, y un denominador chico no achica el
error: lo amplifica y le pone cara de porcentaje, que es peor que no publicarlo,
porque un porcentaje se lee como una medición.

**La regla, en orden de preferencia** (escrita en
[`tradingbot/backtest/cocientes.py`](tradingbot/backtest/cocientes.py), que es de
donde salen los pisos):

1. **Elegir un denominador que contenga al numerador.** Si `B ⊇ A` por
   construcción, el cociente vive en `[0, 1]` y no puede explotar, sin ningún
   piso que calibrar. Es lo que se hizo con la concentración: ganancia **bruta**
   en vez de P&L neto. Cuando esta opción existe es la mejor, porque no tiene
   parámetro.
2. **Si no se puede, exigir un piso explícito sobre `|B|`**, atado a la escala
   natural del denominador y no a un número redondo elegido a ojo.
3. **Debajo del piso va la diferencia absoluta `A − B` con su unidad, y se dice
   por qué** no está el porcentaje. Callar el número sería peor: el lector no
   sabría si la diferencia es chica o si el informe la escondió.

Y una consecuencia que no es obvia: **un cociente cuyo valor normal depende del
tamaño de la muestra se compara contra su propia normal para ese `n`**, no contra
un umbral fijo. Los 5 mejores de 6 ganadores son el 98% por aritmética y los de
50 son el 32%: un umbral de 80% mide cuántos trades hay, no concentración.

Los tres pisos, con de dónde sale cada uno:

| Piso | Valor | Por qué ese |
|---|---|---|
| `PISO_PESOS_SOBRE_R` | 5% del 1R realizado medio | la escala del propio trade. Con 1R ≈ $91 da ~$4.57 |
| `PISO_CAGR` | 0.5 puntos porcentuales anuales | debajo de eso la diferencia entre dos motores es del orden del redondeo del cálculo |
| `PISO_CUENTA` | 10 | una media de menos de diez números le pasa su varianza al cociente |

### La auditoría: todos los cocientes que el informe publica hoy

Se revisaron los que ya había, sin inventar casos nuevos. Cómo queda cada uno:

| Cociente | Denominador | Veredicto |
|---|---|---|
| concentración (5 mejores) | ganancia **bruta** | **regla 1**: el denominador contiene al numerador, vive en `[0,1]` y no necesita piso |
| concentración vs. lo normal | `concentration_baseline(n)` | **la consecuencia**: se compara contra su normal para ese `n`, con piso de cuenta en 10 ganadores |
| error de la lectura ingenua | expectancy en plata | **regla 2 + 3**: piso de pesos; debajo va la diferencia. Es el único que **hoy dispara** de verdad: `ema_cross` v3 tiene $0.67 (no publica el %) y la plantilla de Bollinger $5.11 (publica, y por poco) |
| cotejo de CAGR | CAGR del otro motor | **regla 2 + 3**: piso de CAGR, ahora desde la constante compartida en vez de un `0.005` suelto en el test |
| exigencia del poder (`MDE/disponible`) | efecto disponible | **ya cumplía**: solo se publica si `disponible ≥ MDE`, o sea con el piso puesto en el propio numerador. Más el piso de cuenta en 10 trades afectados |
| `profit_factor` | pérdida bruta | **ya cumplía**: sin perdedores devuelve `inf`, y el informe imprime ∞ |
| `win_loss_ratio` | pérdida media | **estaba mal y se arregló**: devolvía `0.0` sin perdedores, que se imprime "0.00" y se lee como "la ganancia media no vale nada", justo al revés. Ahora contesta `inf`, igual que su hermano |
| Calmar (`CAGR/\|MDD\|`) | max drawdown | **no es un caso, y conviene saber por qué**: `\|MDD\| ≥ \|peor día\|` **siempre** (el drawdown en `t` es al menos la caída de `t`), así que el denominador está acotado por abajo por la volatilidad de la propia serie. El mínimo que produce el repo es −1.40% en `rsi_pullback`, con un peor día de −0.56%. No se le puso piso porque sería código muerto |
| Sharpe, Sortino | desvío de los retornos | **ya cumplían**: devuelven 0 si el desvío es 0 o `nan` |

Lo que cambia en un informe de hoy: nada, salvo que los pisos dejaron de estar
escritos tres veces. El valor de la regla no es el número que arregla sino que la
próxima vez que aparezca un 300% nadie tenga que redescubrir por qué.

---

## 11. Convenciones que conviene no romper

- **La rama canónica es `claude/trading-analysis-bot-8ehd5h` y está escrita
  arriba de todo, en el encabezado de este archivo.** Esto no es burocracia: ya
  pasó dos veces (C12 de la tanda 1, y otra vez al cerrar 2A/2B, que quedaron en
  `claude/trading-bot-trailing-scope-uft7ul`) y las dos veces el proyecto terminó
  con dos historias y con la versión buena de `PLAN.md` y `ESTADO.md` en la rama
  equivocada.

  **Por qué vuelve**: cada sesión del entorno remoto arranca con una rama de
  trabajo *generada automáticamente* (`claude/beautiful-hamilton-4izigp`,
  `claude/trading-bot-trailing-scope-uft7ul`, ...), distinta cada vez, inyectada
  en las instrucciones de la sesión antes de que nadie mire el repo. No hay forma
  de que el entorno adivine la canónica, así que **el default siempre va a estar
  mal** y la corrección tiene que salir del repo.

  **La regla, entonces, es de arranque y no de cierre**: lo primero de cada
  sesión es leer esta línea del `ESTADO.md` y, si la rama asignada no es la
  canónica, hacer
  ```bash
  git checkout -B claude/trading-analysis-bot-8ehd5h origin/claude/trading-analysis-bot-8ehd5h
  ```
  **antes de escribir una línea de código**. Corregirlo al final es peor: para
  entonces ya hay commits en la rama equivocada y alguien tiene que decidir cómo
  reunirlos. (Las dos veces se pudo resolver con fast-forward porque el trabajo
  salió de la canónica; si alguna vez las dos ramas divergen de verdad, esto
  pasa de ser un trámite a ser un merge.)
- **Un commit por bloque de trabajo**, con el mensaje explicando la razón y no
  solo el qué. Los mensajes de este repo son parte de la documentación.
  **Vale aunque dos bloques toquen los mismos archivos**: 2A (el trailing) y 2B
  (`portfolio_risk.py`) se commitearon juntos con el argumento de que compartían
  cuatro archivos, y el argumento no alcanza. Son independientes —se puede querer
  el riesgo de cartera sin el trailing, y al revés— y revertir uno hoy se lleva
  puesto el otro. El commit conjunto quedó, no se rehace; la convención es que no
  se repite.
- **Nada se declara terminado sin evidencia pegada**: salida de `pytest` y del
  backtest, no "listo".
- **Lo que no está implementado se rechaza con un mensaje que lo dice.** Poner
  `trailing_stop:` en un YAML hoy no se ignora en silencio: falla explicando que
  es de la tanda 2. Un backtest que ignora media configuración miente.
- **Los números medidos van fijados en tests.** Si una distribución, una
  correlación o un umbral se midió y se usó para decidir, hay un test que lo
  sostiene, para que el día que cambie se note.
- **Si cambia la calibración de una plantilla, sube `calibration.version` y se
  escribe qué cambió.** Subir la versión sin decirlo es un error de validación.

---

## 12. El trailing como línea base: el análisis, y la decisión que salió de él

> **Decidido el 2026-09-13: el trailing pasa a ser candidata del torneo.** No se
> apaga y no se recalibra: **cambia de estatus**. La línea base pasa a ser hard
> stop + take profit solamente. El cambio está escrito en `PLAN.md`, en "El
> trailing dejó de ser línea base", junto con la posición que ocupa en el orden
> del torneo (después de `break_even`, `time_stop` y `giveback`) y el argumento
> de por qué ahí y no primero. Lo que sigue de esta sección es el análisis que
> sostiene esa decisión, tal como se escribió antes de tomarla.
>
> **Lo que todavía NO está hecho**: la plantilla `ema_cross.yaml` sigue en v3 con
> el chandelier prendido. Apagarlo es un cambio de calibración —sube
> `calibration.version`, cambia todos los números del informe y hay tests que los
> fijan— y va con el código de 2C, no con el PLAN.

La pregunta: el PLAN declara `trailing_stop` línea base ("las plantillas arrancan
con dos capas prendidas"), pero eso se escribió **antes de medir nada**, y el
informe v3 muestra CAGR 1.39% → −0.07%, profit factor 1.43 → 1.02 y los
`take_profit` cayendo de 8 a 2. ¿Sigue teniendo sentido?

### 12.1 ¿Es el chandelier, o son sus dos parámetros?

`scripts/barrido_trailing.py`, `multiple` × `activate_after_r` sobre los dos
universos. Lo que sale tiene dos lecturas y las dos importan.

**Primera: el daño está concentrado, no repartido.** En el universo
independiente la configuración de la plantilla —3 ATR, activa en 1R— es la
**peor celda de toda la grilla** (−0.07%), y 4 ATR con la misma activación da
+1.52%, arriba de las otras pero abajo de la línea base sin trailing (+1.39%…
en realidad la supera). El `take_profit` se recupera en cuanto el trailing se
aleja: 2 sobrevivientes a 3 ATR, 7 a 4 ATR, sobre los 8 de la línea base. O sea
que el mecanismo que el informe insinuaba es real y es **de parámetro**: un
chandelier a 3 ATR armado en +1R persigue al precio lo bastante cerca como para
sacar antes de que el objetivo de 3R se toque.

**Segunda, y es la que manda: los dos universos se contradicen sobre qué celda
conviene.**

| configuración | CAGR indep. | CAGR correlacionado |
|---|---|---|
| SIN trailing | +1.39% | −1.10% |
| 2 ATR · activa 0.5R | **+1.73%** (la mejor) | **−3.15%** (la peor) |
| 3 ATR · activa 1R (la plantilla) | −0.07% (la peor) | −1.30% |
| 4 ATR · activa 0.5R | +1.52% | **−0.42%** (la mejor) |

La celda óptima de un universo es la pésima del otro. Eso **no** es un empate
ruidoso: es la firma de estar midiendo el generador. Dos random walks con
distinta estructura de correlación dan órdenes opuestos, y ninguno de los dos es
el mercado. **La grilla identifica el mecanismo y no puede elegir el
reemplazo**, y esa es toda la conclusión que soporta.

### 12.2 El contrafáctico: qué pasó en cada salida por trailing

`scripts/contrafactico_trailing.py` empareja cada salida por trailing contra el
mismo trade sin la capa. Las 17 del universo independiente (16 `trailing_stop` +
1 `gap_trailing_stop`) y las 34 del correlacionado:

| | independiente | correlacionado |
|---|---|---|
| el trailing **mejoró** el resultado | 10 de 17 (59%) | 24 de 34 (71%) |
| habría terminado **mejor aguantando** | 7 de 17 (41%) | 10 de 34 (29%) |
| ganancia media por rescate | +0.693R | +0.762R |
| pérdida media por corte | −1.913R | −1.952R |
| neto | **−6.46R** (−0.380R/trade) | **−1.24R** (−0.037R/trade) |

**La capa acierta más veces de las que falla y pierde igual.** Ese es el
hallazgo, y no es una opinión sobre el chandelier: es aritmética de la geometría
configurada.

```
hard stop  −1R  ·  take profit  +3R  ·  el trailing se arma en +1R

  rescate máximo posible:  de −1R a ~0R      =  +1R       (acotado por el hard stop)
  corte máximo posible:    de +3R a ~+0.3R   =  −2.7R     (acotado por el objetivo)

  -> hacen falta ~2.7 rescates por cada corte SOLO PARA EMPATAR
```

Y el número medido coincide con la cuenta:

| | ratio de break-even (medido) | ratio real | neto |
|---|---|---|---|
| independiente | 2.76× | 1.43× | −6.46R |
| correlacionado | 2.56× | 2.40× | −1.24R |

En los dos universos el break-even cae en 2.5-2.8 rescates por corte, y el signo
del neto sale de si el ratio real lo alcanza. El correlacionado casi lo alcanza
(2.40 contra 2.56) y por eso queda casi en cero; el independiente no se acerca.

**Lo que es y lo que no es generador-dependiente**, que es la distinción que
salva a este análisis de la etiqueta de la sección 2:

- **No lo es**: el ratio de break-even. Sale de que el hard stop está a −1R y el
  objetivo a +3R, y de que el trailing se arma a +1R. Es la geometría del YAML.
  Sobre cualquier serie, un trailing que se arma en +1R contra un objetivo de 3R
  tiene que rescatar ~2.7 trades por cada uno que corta.
- **Sí lo es**: si el ratio real lo alcanza. Eso depende de con qué frecuencia
  un trade que llegó a +1R sigue hasta +3R en vez de darse vuelta, o sea de
  persistencia y retrocesos — la estructura que en estas series define
  `_ohlcv_from_shocks`.

Dicho de otro modo: **el barrido y el contrafáctico no dicen que el trailing sea
malo. Dicen que la combinación (trailing armado en +1R, objetivo en 3R) le exige
una tasa de acierto alta, y cuál es la tasa real no se puede saber acá.**

### 12.3 La recomendación — aceptada el 2026-09-13

**Que el trailing pase a ser candidata del torneo, no que se apague ni que se
recalibre.** El razonamiento, en orden:

1. **Recalibrar está descartado.** Es la opción que la grilla parece sugerir (4
   ATR se ve mejor que 3 en los dos universos), y es justamente la que no se
   puede tomar: los universos se contradicen sobre el óptimo, así que elegir
   ahí es elegir el generador. Si se tocara el multiplicador habría que hacerlo
   por un argumento estructural, no por la tabla.
2. **Apagarlo tampoco.** El banco A/B da empate y el contrafáctico muestra que la
   capa acierta en el 59-71% de los trades que toca. No hay evidencia de que
   reste; hay evidencia de que **no se sabe**, que es distinto y es el estado que
   corresponde.
3. **Lo que sí cambió es el argumento para tenerla de línea base.** El PLAN la
   puso ahí por diseño, y eso era defendible mientras el costo fuera cero. Ahora
   está medido y no es cero: la §1.2 recalculada muestra que prenderla deja al
   torneo sin ninguna capa medible, `break_even` incluida, que pasa a no
   distinguirse del ruido ni capturando el 100% de su efecto disponible. **Ser
   línea base dejó de ser gratis: cuesta el torneo entero.**
4. Y hay una asimetría que decide: una capa que compite puede terminar prendida
   —si gana, queda—, mientras que una capa que es línea base **no puede terminar
   apagada jamás**, porque nunca se la mide. Con los grados de libertad que hay,
   el default caro es el que no se puede revisar.

**Qué implica, ya decidido**: `trailing_stop` entra al orden del torneo de 2C, la
línea base pasa a ser hard stop + take profit solos, y la §1.2 del PLAN vuelve a
la columna "sin trailing". Las plantillas arrancan con el trailing apagado hasta
que gane, con el motivo escrito, como cualquier otra capa. El costo es que
contradice una regla del PLAN escrita explícitamente, y por eso la decisión fue
del usuario y no de la sesión que hizo el análisis.

**Lo que el análisis NO recomendaba**, y conviene tenerlo presente porque la
decisión se tomó igual y con razón: apagar o recalibrar el trailing antes de
tener los CSV reales. Cambiar de **estatus** no es ninguna de las dos cosas —no
resuelve si el trailing aporta, **habilita** que se mida—, así que no depende del
número que falta. El número que decide si el trailing se queda —cuántos trades
que llegan a +1R siguen hasta +3R— es una propiedad del mercado y sigue sin
existir; por eso el trailing queda como candidata y no como capa descartada.

---

## 13. La tolerancia de la validación de precios: por qué 1e-9 y por qué no 1e-6

Bajando los fixtures reales por primera vez en una máquina con salida a Yahoo,
`fetch_fixture.py SPY --years 15` frenó con:

    SPY: 1 velas con open/close fuera del rango [low, high], p.ej. 2018-01-19

y el dato no está roto. Ese día SPY cerró en su máximo, o sea que en la serie
sin ajustar `close` **es** `high`, el mismo número. El ajuste retroactivo
multiplica las dos columnas por el mismo factor pero con distinto orden de
operaciones, y el resultado no es bit-idéntico: `close` llega 2.8e-14 arriba de
`high` sobre precios de ~246, exactamente **un ULP** de float64.

No es una rareza de un símbolo. Con ~3800 velas por símbolo y 13 símbolos,
cualquier día que cierre en el máximo o abra en el mínimo puede disparar lo
mismo, y son días comunes.

**La tolerancia elegida es `PRICE_REL_TOL = 1e-9`**, y sale de acotar los dos
extremos que tiene que separar:

| | Magnitud relativa | De dónde sale |
|---|---|---|
| Ruido de punto flotante | ~1e-13 | un ULP es 2.2e-16; el ajuste encadena productos acumulados a lo largo de la serie, así que cientos de ULP es un techo generoso |
| Inconsistencia genuina más chica | ~1e-5 | un feed roto pone el cierre fuera del rango por al menos un tick de un centavo: 1e-5 sobre un instrumento de $1000, 4e-5 sobre los ~$250 de SPY |

1e-9 es el punto medio geométrico: cuatro órdenes de magnitud por encima del
ruido y cuatro por debajo del error más chico que vale la pena rechazar. No es
un número redondo elegido a ojo, es el centro del hueco de ocho órdenes que hay
entre las dos cosas que el chequeo tiene que distinguir.

**Por qué NO se unificó con el `TOLERANCE = 1e-6` de `data/cache.py`**, aunque
los dos absorban ruido de punto flotante y unificar sea tentador: **responden
preguntas distintas y tienen costos de error distintos**.

- El de `cache.py` compara la misma vela bajada dos veces para decidir si Yahoo
  reajustó la serie. Equivocarse por lo bajo cuesta **una descarga de más**, que
  es molesto y nada más. Y el error genuino que busca —un dividendo— es del
  orden de 1e-3, así que 1e-6 le sobra por tres órdenes.
- El de `validate.py` decide si datos rotos entran a un backtest. Equivocarse
  por lo alto **no cuesta nada visible**: da un resultado perfecto y falso, que
  es el modo de falla que este repo trata como el peor de todos.

Para el chequeo que importa se toma el valor más ajustado que igual absorbe el
ruido, no el número que ya estaba escrito en otro lado. La consistencia entre
módulos no es un argumento cuando los módulos no están haciendo lo mismo.

**Qué chequeos llevan tolerancia y cuáles no.** Solo los que comparan un precio
de la vela contra otro precio de la misma vela, porque son los únicos donde el
dato original tiene dos columnas que valen lo mismo y el ajuste las separa: son
cuatro (`high < low`, `open` y `close` contra `high` y contra `low`). Los otros
no la necesitan y no la llevan: `precio <= 0` compara contra una constante,
el volumen es un entero que el factor de ajuste de precios no toca, el salto de
50% es un umbral de criterio y no un punto donde dos números que deberían ser
iguales se separan, y el calendario compara fechas. El razonamiento está también
en el docstring de `validate_ohlcv`, para que no haya que venir acá.

### El corolario: los reintentos no eran para esto

La misma corrida mostró un segundo problema. El script reintentó **tres veces
con backoff** (2s, 4s) una falla de validación, que es determinística: la serie
llegó entera y los tres intentos bajan los mismos bytes y los rechazan por el
mismo motivo. Seis segundos para llegar al mismo resultado, y multiplicado por
13 símbolos.

La separación quedó en `EmptySeriesError`, subclase de `DataValidationError`.
Es la única falla de validación que puede ser transitoria, porque **el 429 de
Yahoo no llega como excepción de red sino como serie vacía** —esa es la razón
por la que la serie vacía estaba metida en el mismo cajón que todo lo demás—.
`es_transitorio` reintenta eso y cualquier cosa que no sea un
`DataValidationError`; el resto corta en el primer intento.

---

## 14. La línea base sobre datos reales: la hipótesis, confirmada

*(2026-09-15. Antes de esto, ningún número de este proyecto sobre si la
estrategia "funciona" venía de mercado real — todo lo de las secciones 2 y 12
son fixtures sintéticos, con la etiqueta de alcance puesta a propósito. Esto
es lo primero que corre sobre los 13 ETFs reales con el cash ya corregido
(sección de arriba en `PLAN.md`, "Cash real: antes de medir nada"), y responde
una sola pregunta: ¿vale la pena seguir invirtiendo en capas de salida antes de
saber si la entrada tiene algo que administrar?*

### La corrida

```
tradingbot backtest -s config/strategies/ema_cross_sin_trailing.yaml \
                    -d tests/fixtures/real \
                    --symbol XLK --symbol XLF --symbol XLE --symbol XLV --symbol XLI \
                    --symbol XLY --symbol XLP --symbol XLU --symbol XLB --symbol XLRE \
                    --symbol SPY --symbol QQQ --symbol IWM
```

`ema_cross_sin_trailing` y no `ema_cross`: es la línea base real del PLAN (hard
stop + take profit, sin ninguna capa del torneo prendida — el trailing sigue
siendo candidata, sección 12). Los 13 ETFs son el universo elegido en la
sección 1 (sesgo de supervivencia casi nulo). El informe completo, sin
abreviar:

```
================================================================
BACKTEST · ema_cross_trend_filter_sin_trailing
================================================================
Símbolos      : IWM, QQQ, SPY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY
Calibración   : v4 (2026-09-15) · initial_cash 10000 -> 100000, igual que ema_cross.yaml v4 y por el mismo motivo: el sizing degenerado por falta de cash (PLAN.md, "Cash real: antes de medir nada"). Comparte calibración de entrada con ella (max_position_pct 30, risk_pct 1.0), que es lo que hace que el banco A/B mida la capa y no dos estrategias distintas.
Período       : 2010-01-04 → 2025-12-30  (4023 velas)
                RANGO RECORTADO: el YAML pedía desde 2010-01-01 y hasta 2025-12-31; los datos disponibles van de 2010-01-04 a 2025-12-30
Costos        : comisión 0.05% + slippage 0.05% por lado
Ejecución     : señal al cierre de t, fill en la apertura de t+1 (next_open)

Buy & hold    : cartera equiponderada de 13 símbolos (IWM, QQQ, SPY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY), $7,692 en cada uno
SPY           : buy & hold de SPY · CSV local (tests/fixtures/real/SPY.csv) · ya está en el universo
                SPY está en el universo: cuenta en las dos columnas

Métrica                         Estrategia      Buy & hold             SPY
--------------------------------------------------------------------------
Equity final                      $217,573        $655,262        $769,497
Retorno total                      117.57%         555.26%         669.50%
CAGR                                 4.98%          12.48%          13.61%
Max drawdown                       -13.01%         -34.23%         -33.72%
Duración de ese DD                   946 d           173 d           173 d
DD más largo                         946 d           709 d           709 d
Sharpe                                0.69            0.81            0.85
Sortino                               0.80            0.96            1.01
Calmar                                0.38            0.36            0.40
Profit factor                         1.80
Win rate                            41.37%
Expectancy                          +0.46R
Expectancy en plata               $+462.73
Retorno s/ riesgo desplegado          43.77%
Riesgo real medio (1R)           $1,057.29
Ganancia/pérdida media                2.55
Trades                                 249
Racha de pérdidas                       13
Costo de la peor racha         $-23,345.69
5 mejores vs. lo normal              0.59×
Días con posición                   80.61%

Fiabilidad    : razonable (249 trades)
Costos totales: comisión $8,901.06 + slippage $8,901.10

Salidas por regla
----------------------------------------------------------
Motivo                Trades     %     P&L medio   R medio
hard_stop                 87   35%       $-1,073    -1.05R
take_profit               82   33%        $2,994    +2.94R
signal                    57   23%         $-128    -0.12R
gap_stop                  23    9%       $-1,292    -1.19R

Unidad de riesgo
----------------------------------------------------------
  1R declarado por el YAML (risk_pct 1.0%)        $1,484.74
  1R realizado (acciones × riesgo por acción)     $1,057.29   (0.71× del declarado)
  Expectancy (media de pnl_r)                     +0.46R
  Expectancy en plata (media de pnl)              $+462.73
  Retorno sobre riesgo desplegado (Σpnl/Σriesgo)  +43.77%
  Quién decidió el tamaño                         riesgo 64, tope 123, cash 69 (de 256 señales)
       risk_pct NO decidió el tamaño en 192 de 256 señales.
  AVISO: risk_pct queda decorativo en buena parte de los trades: la distancia típica al stop es 2.68% del precio y el tope de concentración manda por debajo de risk_pct/max_position_pct = 3.33% (71% de las barras). Subir max_position_pct o ensanchar el stop devuelve el control a risk_pct.
  OJO: leer la expectancy como '+0.46R × $1,484.74' da $+689.33 por trade,
       y el promedio real es $+462.73. Esa lectura se equivoca 49%.

Heat de cartera (Σ riesgo real abierto / equity)
----------------------------------------------------------
  máximo                          4.32%
  medio (días con posición)       1.92%
  días con heat > 0               3243
  tope                        sin definir (max_portfolio_heat_r apagado)

PODER DE MEDICIÓN — cuánto efecto hace falta para distinguir una capa del ruido
  n = 249 trades · σ del efecto = 1.47R (estimada, ver poder.py) · α = 0.05 · potencia = 80%

  fracción de trades      MDE por trade      MDE sobre la
  que la capa toca         afectado          expectancy global
         100%                0.26R                0.26R
          75%                0.30R                0.23R
          50%                0.37R                0.18R
          25%                0.52R                0.13R
          15%                0.67R                0.10R

  capa             afect    f     MDE/afect  disponible  cota       veredicto
  trailing_stop    149   0.60      0.34R      1.16R  superior   necesita capturar el 29% del efecto disponible
  break_even        47   0.19      0.60R      0.87R  inferior   necesita capturar el 69% del efecto disponible
  giveback          44   0.18      0.62R      1.48R  inferior   necesita capturar el 42% del efecto disponible
  time_stop        147   0.59      0.34R      1.88R  superior   necesita capturar el 18% del efecto disponible
  market_regime     35   0.14      0.70R      1.39R  exacta     necesita capturar el 50% del efecto disponible
  reversal           —      —          —           —      —          no estimable sin la capa: depende de siete señales que todavía no existen. Su f la mide el banco cuando la capa esté escrita
  event_risk         —      —          —           —      —          no estimable sin red: necesita fechas de earnings (Ticker.earnings_dates). Queda fuera del torneo por decisión escrita en el PLAN

  trailing_stop NO es candidata del torneo: entra por decisión de diseño del PLAN
  (línea base de las plantillas). Su fila está para dimensionar, no para decidir:
  con este universo y este período el poder no alcanza para afirmar que aporta.

  'disponible' es el mejor caso de la capa sobre los trades que toca, medido
  sobre los trades ya cerrados: capturar toda la R que quedó sobre la mesa. Ninguna
  capa real captura todo (un chandelier devuelve 3 ATR antes de sacarte), así que el
  veredicto se lee como exigencia: si dice 65%, la capa tiene que capturar dos tercios
  de todo lo disponible para que el resultado se distinga de un empate.

Posiciones abiertas al cierre del período: 4 (fuera de las estadísticas de trades, valuadas al último cierre)
----------------------------------------------------------
  IWM    entrada 2025-11-28 · 213 acciones · valuada $52,585 (+75 = +0.03R)
  XLF    entrada 2025-12-08 · 623 acciones · valuada $34,065 (+963 = +1.17R)
  XLI    entrada 2025-12-05 · 421 acciones · valuada $65,474 (+674 = +0.40R)
  XLY    entrada 2025-12-05 · 547 acciones · valuada $65,541 (+641 = +0.30R)

In-sample / out-of-sample (corte 2020-12-31)
----------------------------------------------------------
Tramo                    CAGR        MDD  Trades   Expect.    Fiabilidad
in-sample               4.51%    -13.01%     155    +0.48R     razonable
out-of-sample           6.21%    -12.62%      94    +0.44R         débil

 · La estrategia (5.0% CAGR) rinde menos que comprar y esperar (12.5%). Por ahora no justifica operar.

 · Universo elegido con información posterior: los resultados sobre acciones que hoy existen son optimistas (sesgo de supervivencia).

Señales rechazadas: 74
(el backtest refleja las señales que realmente se habrían podido tomar)
----------------------------------------------------------
Categoría                 Señales     %   Qué la produjo
lugares ocupados               31   42%   max_open_positions alcanzado
cash                           43   58%   no alcanzaba la plata para comprar ni una acción

  detalle por motivo:
    40  no hay cash para comprar ni 1 acción
    31  max_open_positions alcanzado
     3  sin cash al momento del fill

Manifiesto    : 005ab7aee382d253  (datos e016ae9131e4ae31)
```

### La tabla que pediste, lado a lado

| métrica | Estrategia | Buy & hold equiponderado | SPY |
|---|---|---|---|
| CAGR | **4.98%** | 12.48% | 13.61% |
| Max drawdown | **-13.01%** | -34.23% | -33.72% |
| Sharpe | **0.69** | 0.81 | 0.85 |
| Sortino | 0.80 | 0.96 | 1.01 |
| Calmar (CAGR/\|MDD\|) | 0.38 | 0.36 | 0.40 |
| Retorno s/ riesgo desplegado | 43.77% | no aplica | no aplica |

`return_on_risk` no tiene análogo en un buy & hold: esa métrica pondera cada
trade por la plata que puso en riesgo, y un buy & hold no arriesga una
cantidad declarada por trade, mantiene la posición entera. Está para leer la
columna de la estrategia sola, no para compararla con las otras dos.

### 2.3 — ¿Se confirma la hipótesis? Sí, y con un matiz que importa

**En CAGR, que es la pregunta que se hizo, sí: la estrategia rinde menos de la
mitad que comprar y esperar equiponderado (4.98% contra 12.48%) y todavía menos
que SPY solo (13.61%).** In-sample y out-of-sample dan el mismo signo (4.51% y
6.21%, los dos muy por debajo de cualquiera de los dos benchmarks), así que no
es un artefacto del corte. `render_console` ya lo dice en su propia línea: *"La
estrategia (5.0% CAGR) rinde menos que comprar y esperar (12.5%)."*

**El matiz, porque los números de al lado no cuentan la misma historia si se
los mira sueltos.** La estrategia no tiene expectancy negativa ni un motor sin
filo: `profit factor` 1.80, `win rate` 41%, expectancy +0.46R, `return_on_risk`
+43.77%. Cada peso que la estrategia puso en riesgo devolvió 44 centavos de
ganancia — eso es un sistema con edge, no uno roto. Y el drawdown lo confirma
del otro lado: -13.01% contra el -34% de los dos benchmarks, un tercio del
dolor. Calmar, que es CAGR sobre ese dolor, queda **por encima** del buy & hold
equiponderado (0.38 contra 0.36) y apenas debajo de SPY (0.40): con la vara del
riesgo tolerado, la distancia se achica mucho.

**Entonces el problema no es "la entrada no tiene nada que administrar"; es
que lo que tiene no alcanza a compilarse en CAGR con esta exposición.** `Días
con posición: 80.61%` cuenta cuántos días hay *al menos una* posición abierta,
no cuánto del capital está invertido: con `max_open_positions: 5` y
`max_position_pct: 30`, el capital nunca puede estar más del 5×30% = 150%
nominal expuesto, y en la práctica bastante menos —`riesgo 64, tope 123, cash
69 de 256 señales`: el 27% de las señales entra recortada por falta de cash,
justo la fricción que sección 1 mide y que $100.000 alivia sin eliminar—. Un
buy & hold está 100% invertido todo el tiempo por definición; esta estrategia
compra fracciones de la cartera y las vende de vuelta, muchas veces al año.
Con edge positivo pero exposición muy por debajo de 100%, el CAGR compuesto
queda muy por debajo del de un instrumento que está siempre adentro, aunque el
sistema "funcione" trade a trade.

**Esto sí es la respuesta a la pregunta que abrió la sesión.** El problema no
está en que la entrada no tenga nada que ofrecer —tiene expectancy y
`return_on_risk` positivos, medidos sobre mercado real por primera vez— sino en
que **ninguna capa de salida del torneo (sección 12, PLAN.md "El torneo de
capas") puede cerrar la brecha de exposición**: las siete capas actúan sobre
posiciones ya abiertas, deciden cuándo salir de un trade que ya existe. Ninguna
decide *cuántas* posiciones tener a la vez ni *qué tan grande* es cada una —eso
lo deciden `risk_pct`, `max_position_pct` y `max_open_positions`, que son
`risk/`, no `exits/`—. Prender el trailing, el break-even o cualquier otra capa
puede mover el 4.98% unas décimas para arriba o para abajo; no lo va a acercar
al 12-13% de estar siempre invertido, porque esa distancia no la abre ni la
cierra ninguna regla de salida. **Esta sesión no decide qué hacer con eso — la
consigna es parar acá con el número en la mano.**
