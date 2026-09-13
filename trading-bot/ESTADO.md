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
  en la sección 10: pasó dos veces).

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
  como línea base (no como candidata: el plan ya la declara prendida).
- **2B**: riesgo de cartera. Va en el medio y no al final porque cambia el tamaño
  de las posiciones, y el tamaño cambia toda expectancy en pesos: si el torneo
  corre primero, sus mediciones quedan obsoletas el día que entra el heat.
- **2C**: el torneo, de a una, en orden de grados de libertad creciente, con una
  pasada final donde las capas descartadas se reevalúan contra la configuración
  ganadora. **PARADO hasta que haya CSV reales**, por la razón de la sección 2:
  sobre series sintéticas el torneo mediría el generador y no el mercado, y eso
  no lo arregla generar más trades.

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
- Por eso `trailing_stop` entra en 2A **por decisión de diseño del PLAN** (línea
  base de las plantillas) y no como capa validada, y el informe lo dice donde
  aparece el trailing.
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

## 10. Convenciones que conviene no romper

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
