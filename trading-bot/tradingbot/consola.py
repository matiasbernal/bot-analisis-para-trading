"""La salida de texto se fuerza a UTF-8, y la decisión está acá porque tiene fundamento.

**El problema.** El informe escribe ``→`` (fill, atribución de salidas), ``σ``
(el poder de medición), ``·`` (separadores) y acentos del castellano. En una
consola cp1252 —el default de Windows fuera de Windows Terminal— escribir
``→`` levanta ``UnicodeEncodeError`` y el proceso muere. Y muere **después** de
correr el backtest entero: el cómputo ya está hecho, lo que se pierde es el
informe. Lo mismo pasa cuando la salida va a un pipe o a un archivo, porque ahí
Python tampoco usa UTF-8 sino la codificación local.

**Por qué se fuerza acá y no es problema del usuario.** Los tres argumentos, en
orden de peso:

1. *Los caracteres los elegimos nosotros.* No vienen del mercado ni de un
   archivo del usuario: están escritos en `reporting/report.py`. Hacer que el
   informe dependa de la página de códigos de la terminal es hacer que dependa
   de algo que no tiene nada que ver con lo que el informe dice.
2. *Un redirect tiene que dar el mismo archivo en las tres plataformas.*
   ``tradingbot backtest > informe.txt`` en Windows escribía cp1252 y en Linux
   UTF-8: el mismo comando, dos archivos distintos, y el de Windows ni siquiera
   se podía escribir. Un informe es un artefacto, y un artefacto con
   codificación variable no se puede diffear ni archivar.
3. *El modo de falla que se cambia es el correcto.* Antes: el proceso revienta y
   se pierde todo. Ahora: como mucho, una consola vieja dibuja mal un glifo y
   los números —que es lo que se vino a leer— salen igual. Además el usuario
   puede arreglar su consola (``chcp 65001``, o Windows Terminal, que ya viene
   en UTF-8); lo que no puede arreglar es el crash.

Lo que **no** se hace: tocar variables de entorno (``PYTHONIOENCODING``,
``PYTHONUTF8``). Una variable de entorno arregla la máquina del que la puso, no
el programa, y se pierde en el primer cron, CI o doble clic.
"""

from __future__ import annotations

import sys

#: la codificación de toda salida de texto del programa, en todas las plataformas
CODIFICACION = "utf-8"


def forzar_utf8() -> None:
    """Reconfigura stdout y stderr a UTF-8. Idempotente y sin efecto si no se puede.

    ``reconfigure`` existe en los ``TextIOWrapper`` de Python 3.7+; bajo pytest,
    o con la salida capturada por otra herramienta, ``sys.stdout`` puede ser otro
    objeto que no lo tenga, y ahí no hay nada que forzar (ese objeto ya decide su
    propia codificación).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigurar = getattr(stream, "reconfigure", None)
        if reconfigurar is None:
            continue
        try:
            reconfigurar(encoding=CODIFICACION)
        except (OSError, ValueError):  # pragma: no cover - stream ya cerrado o detached
            pass
