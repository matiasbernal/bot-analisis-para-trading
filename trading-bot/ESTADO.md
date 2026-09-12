# Estado del proyecto

Este archivo es para alguien que llega sin haber estado en las conversaciones que
llevaron hasta acá. Cuenta **dónde está el proyecto, qué se decidió y por qué**.
Lo que el código hace está en el código; lo que hay acá son las razones, que es
lo único que no se puede reconstruir leyéndolo.

- El diseño original está en [`PLAN.md`](PLAN.md). Sigue siendo la referencia,
  con dos correcciones marcadas dentro del propio archivo (cómo se calcula el
  heat, y qué puede decir la alerta).
- Cómo usar la herramienta está en [`README.md`](README.md).
- Rama de trabajo: `claude/trading-analysis-bot-8ehd5h`.

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
  ganadora.

Las dos decisiones de fondo que conviene no re-discutir sin leer el fundamento:
cada capa se decide con walk-forward **dentro del in-sample** y el out-of-sample
se gasta una sola vez al final del torneo (seis decisiones contra el OOS lo gastan
seis veces: ~26% de probabilidad de quedarse con al menos una capa inútil), y el
resultado del torneo **depende del orden**, así que el orden se registra con el
resultado.

---

## 2. Por qué `max_position_pct` es 30 y no 20

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

## 3. El sesgo ATR: dormido, no resuelto

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

## 4. La unidad de riesgo: `return_on_risk` y el heat

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

---

## 5. El formato de alerta decidido (Fase 4, sin implementar)

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

## 6. El universo correlacionado y para qué está cada grupo

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

## 7. Qué está deliberadamente afuera, y por qué

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

## 8. Qué números del informe cambiaron respecto de la tanda 1

La plantilla `ema_cross` declara su calibración en el YAML y el informe la imprime
en el encabezado, justamente para que dos informes de la misma estrategia no se
confundan. **v1 = `max_position_pct: 20`; v2 = `30`.** Sobre el mismo fixture:

| | v1 (tope 20) | v2 (tope 30) |
|---|---|---|
| Equity final | $10.486 | $10.681 |
| CAGR | 1.00% | 1.39% |
| Max drawdown | −4.96% | −5.51% |
| Duración de ese DD | 957 d | 371 d |
| DD más largo | 957 d | 385 d |
| In-sample CAGR | −0.17% | +0.18% |
| Out-of-sample CAGR | 2.82% | 3.26% |
| Expectancy | +0.25R | +0.25R |
| Expectancy en plata | $+17.27 | $+24.51 |
| 1R realizado promedio | $78.53 | $95.89 |
| Error de la lectura ingenua | 45% | 3% |

Todo es consecuencia del mismo cambio: posiciones más grandes ganan y pierden
más. El drawdown más profundo empeora (−4.96% → −5.51%) y a la vez dura mucho
menos, y eso tiene una explicación verificada a mano: **no es el mismo drawdown
más corto, es un episodio largo que se parte en dos** porque la equity ahora sí
recupera su máximo en el medio.

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

## 9. Convenciones que conviene no romper

- **Un commit por bloque de trabajo**, con el mensaje explicando la razón y no
  solo el qué. Los mensajes de este repo son parte de la documentación.
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
