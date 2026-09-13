"""La codificación es explícita en todas partes, y eso se verifica desde Linux.

**El bug que estos tests cierran** son dos capas del mismo problema, y las dos
solo se manifiestan en Windows:

1. El subproceso **escribe** ``→`` y ``σ`` y la consola cp1252 no los puede
   codificar: ``UnicodeEncodeError`` y el proceso muere después de haber corrido
   el backtest entero.
2. ``subprocess.run(text=True)`` **lee** con la codificación por defecto de la
   plataforma, así que ``Señales rechazadas`` llega como ``SeÃ±ales rechazadas``
   y el assert no encuentra el string.

Los dos se tapan con ``PYTHONIOENCODING=utf-8 PYTHONUTF8=1``, y taparlos así es
exactamente lo que no queremos: arregla la máquina del que puso la variable, no
el programa, y se pierde en el primer cron o CI.

**Por qué estos tests fallan igual desde Linux.** No se puede reproducir Windows
acá, pero sí se puede reproducir el mecanismo: ``PYTHONIOENCODING=cp1252`` hace
que un Python de Linux levante el mismo ``UnicodeEncodeError`` en el mismo
carácter. Eso cubre la capa 1. La capa 2 no tiene manifestación en Linux —el
default local ya es UTF-8— así que se verifica sobre el árbol sintáctico: toda
llamada que decodifica texto tiene que nombrar su codificación. Un
``subprocess.run(..., text=True)`` nuevo sin ``encoding`` pone este archivo en
rojo en cualquier plataforma, que es lo que se pedía.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path



RAIZ = Path(__file__).resolve().parents[1]
ARBOLES = ("tradingbot", "scripts", "tests")

#: llamadas que decodifican o codifican texto y por lo tanto tienen que decir con qué
LEEN_O_ESCRIBEN_TEXTO = {"read_text", "write_text", "read_csv", "to_csv", "open"}
SUBPROCESO = {"run", "check_output", "Popen", "check_call", "call"}


def _fuentes() -> list[Path]:
    archivos = [p for arbol in ARBOLES for p in (RAIZ / arbol).rglob("*.py")]
    assert len(archivos) > 40, "no se encontraron las fuentes: revisá ARBOLES"
    return sorted(archivos)


def _nombre(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _kwargs(call: ast.Call) -> dict[str, ast.expr]:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


def _es_texto_en_memoria(call: ast.Call) -> bool:
    """``pd.read_csv(io.StringIO(texto))`` no toca disco: ahí no hay nada que codificar."""
    return bool(call.args) and isinstance(call.args[0], ast.Call)


def _es_binario(kwargs: dict[str, ast.expr]) -> bool:
    modo = kwargs.get("mode")
    return isinstance(modo, ast.Constant) and "b" in str(modo.value)


#: dónde cae ``encoding`` cuando se pasa por posición y no por nombre
POSICION_DE_ENCODING = {"read_text": 0, "write_text": 1, "open": 3}


def _encoding_por_posicion(nombre: str, call: ast.Call) -> bool:
    """``path.read_text("utf-8")`` es tan explícito como ``encoding="utf-8"``."""
    indice = POSICION_DE_ENCODING.get(nombre)
    return indice is not None and len(call.args) > indice


def _hallazgos(ruta: Path) -> list[str]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    faltantes: list[str] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        nombre = _nombre(nodo.func)
        kwargs = _kwargs(nodo)
        if "encoding" in kwargs:
            continue
        donde = f"{ruta.relative_to(RAIZ)}:{nodo.lineno}"

        if nombre in SUBPROCESO:
            # sin `text`/`universal_newlines` la salida son bytes y los decide
            # quien los decodifique después; con ellos, los decide el locale
            decodifica = any(
                isinstance(kwargs.get(k), ast.Constant) and kwargs[k].value
                for k in ("text", "universal_newlines")
            )
            if decodifica:
                faltantes.append(f"{donde}  subprocess.{nombre}(text=True) sin encoding")
        elif nombre in LEEN_O_ESCRIBEN_TEXTO:
            if _encoding_por_posicion(nombre, nodo):
                continue
            if nombre == "to_csv" and not nodo.args:
                continue  # to_csv() sin path devuelve un str: no hay bytes
            if nombre == "read_csv" and _es_texto_en_memoria(nodo):
                continue
            if nombre == "open" and _es_binario(kwargs):
                continue
            faltantes.append(f"{donde}  {nombre}(...) sin encoding")
    return faltantes


def test_ninguna_llamada_de_texto_deja_la_codificacion_implicita():
    """El árbol entero, no una lista de archivos: un módulo nuevo también entra."""
    faltantes = [h for ruta in _fuentes() for h in _hallazgos(ruta)]
    assert faltantes == [], (
        "codificación implícita (rompe en Windows, pasa en Linux):\n  "
        + "\n  ".join(faltantes)
        + "\n\nPoné encoding=\"utf-8\". Ver tradingbot/consola.py."
    )


def test_todo_punto_de_entrada_fuerza_la_codificacion_de_salida():
    """La CLI y los scripts: los dos imprimen σ y →, los dos revientan en cp1252.

    Se verifica sobre el árbol y no sobre una lista, así que un script nuevo que
    se olvide de llamar a ``forzar_utf8()`` pone esto en rojo desde Linux.
    """
    entradas = [RAIZ / "tradingbot" / "cli.py", *sorted((RAIZ / "scripts").glob("*.py"))]
    sin_forzar = [
        str(p.relative_to(RAIZ))
        for p in entradas
        if "def main(" in p.read_text(encoding="utf-8")
        and "forzar_utf8()" not in p.read_text(encoding="utf-8")
    ]
    assert sin_forzar == [], (
        "puntos de entrada que no fuerzan UTF-8 en la salida: " + ", ".join(sin_forzar)
    )


def _correr_cli_en_cp1252(*argumentos: str) -> subprocess.CompletedProcess:
    """La CLI con la consola en cp1252, que es lo que Windows le da por defecto."""
    entorno = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    entorno.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, "-m", "tradingbot.cli", *argumentos],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=RAIZ,
        env=entorno,
    )


def test_una_consola_cp1252_no_voltea_el_informe():
    """El informe sale entero, con σ y → adentro, sin variables de entorno.

    Sin ``forzar_utf8()`` esto termina en ``UnicodeEncodeError: 'charmap' codec
    can't encode character '\\u2192'`` con el backtest ya corrido: el cómputo
    hecho y el informe perdido.
    """
    proceso = _correr_cli_en_cp1252(
        "backtest",
        "--strategy", "config/strategies/cartera_correlacionada.yaml",
        "--data", "tests/fixtures/correlated",
    )
    assert proceso.returncode == 0, proceso.stderr[-2000:]
    assert "UnicodeEncodeError" not in proceso.stderr
    assert "→" in proceso.stdout, "el informe perdió las flechas de la atribución de salidas"
    assert "Señales rechazadas" in proceso.stdout


def test_la_consola_cp1252_tampoco_voltea_el_banco_ab():
    """El otro camino de salida, que es el que imprime σ."""
    proceso = _correr_cli_en_cp1252(
        "comparar",
        "--base", "config/strategies/ema_cross_sin_trailing.yaml",
        "--variante", "config/strategies/ema_cross.yaml",
        "--data", "tests/fixtures/synthetic",
        "--replicas", "100",
    )
    assert proceso.returncode == 0, proceso.stderr[-2000:]
    assert "σ" in proceso.stdout, "el bloque de poder perdió el σ"

def test_forzar_utf8_no_se_cae_con_una_salida_capturada(capsys):
    """Bajo pytest ``sys.stdout`` no es un TextIOWrapper y no tiene ``reconfigure``.

    Es el caso que hace que ``forzar_utf8()`` tenga que ser tolerante en vez de
    asumir el stream real: si reventara acá, reventaría en cualquier herramienta
    que capture la salida.
    """
    from tradingbot.consola import forzar_utf8

    forzar_utf8()
    print("σ y →")
    assert capsys.readouterr().out.strip() == "σ y →"
