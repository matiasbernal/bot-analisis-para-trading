"""El informe HTML, verificado con Playwright a 390, 412 y 1280 px.

Mobile-first no es "que se vea bien en el celular": es que a 390 px no haya
scroll horizontal, que los gráficos midan lo que mide su contenedor y que nada
que haya que tocar sea más chico que 44 px.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import make_strategy

from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.manifest import build_manifest
from tradingbot.config import load_strategy
from tradingbot.reporting.report import render_console, render_html

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright no está instalado"
).sync_playwright

#: el entorno del sandbox trae Chromium acá; en tu máquina lo pone `playwright install`
CHROMIUM_FALLBACK = Path("/opt/pw-browsers/chromium")

ANCHOS = [390, 412, 1280]


def _launch(playwright):
    try:
        return playwright.chromium.launch()
    except Exception:
        if CHROMIUM_FALLBACK.exists():
            return playwright.chromium.launch(executable_path=str(CHROMIUM_FALLBACK))
        pytest.skip("no hay Chromium: corré `playwright install chromium`")


@pytest.fixture(scope="module")
def informe(tmp_path_factory):
    frames_config = load_strategy("config/strategies/ema_cross.yaml")
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from fixtures.synthetic import synthetic_universe

    from tradingbot.data.validate import validate_ohlcv

    frames = {
        symbol: validate_ohlcv(df, symbol)
        for symbol, df in synthetic_universe(frames_config.universe).items()
    }
    result = run_backtest(frames_config, frames)
    manifest = build_manifest(frames_config, frames, result.metrics)
    path = tmp_path_factory.mktemp("informe") / "report.html"
    render_html(result, frames, manifest, path, plotly="inline")
    return path


def test_el_informe_se_genera_y_trae_lo_obligatorio(informe):
    html = informe.read_text(encoding="utf-8")
    assert "Buy &amp; hold" in html or "Buy & hold" in html  # benchmark obligatorio
    assert "Drawdown" in html and "Trades" in html
    assert "sesgo de supervivencia" in html
    assert "plotly" in html.lower()


def test_el_informe_de_consola_trae_el_benchmark_al_lado(informe):
    frames_config = load_strategy("config/strategies/ema_cross.yaml")
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from fixtures.synthetic import synthetic_universe

    from tradingbot.data.validate import validate_ohlcv

    frames = {
        symbol: validate_ohlcv(df, symbol)
        for symbol, df in synthetic_universe(frames_config.universe).items()
    }
    texto = render_console(run_backtest(frames_config, frames))
    assert "Buy & hold" in texto
    assert "CAGR" in texto and "Max drawdown" in texto
    assert "Salidas por regla" in texto


@pytest.mark.playwright
@pytest.mark.parametrize("ancho", ANCHOS)
def test_sin_scroll_horizontal(informe, ancho, tmp_path):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page(viewport={"width": ancho, "height": 844})
        page.goto(informe.as_uri())
        page.wait_for_timeout(1200)  # que Plotly termine de dibujar

        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        inner_width = page.evaluate("window.innerWidth")
        assert scroll_width <= inner_width, (
            f"a {ancho}px la página scrollea en horizontal ({scroll_width} > {inner_width})"
        )

        page.screenshot(path=str(tmp_path / f"informe_{ancho}.png"), full_page=False)
        browser.close()


@pytest.mark.playwright
def test_a_390_los_graficos_entran_y_los_toques_son_alcanzables(informe):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(informe.as_uri())
        page.wait_for_timeout(1200)

        # cada gráfico mide lo que mide su contenedor, y tiene alto relativo
        anchos = page.evaluate(
            """() => Array.from(document.querySelectorAll('.chart')).map(c => {
                const plot = c.querySelector('.js-plotly-plot');
                return [c.clientWidth, plot ? plot.clientWidth : 0,
                        plot ? plot.clientHeight : 0];
            })"""
        )
        assert anchos, "el informe no tiene gráficos"
        for contenedor, grafico, alto in anchos:
            assert grafico <= contenedor + 1, "el gráfico se sale de su contenedor"
            assert grafico > contenedor * 0.8, "el gráfico no usa el ancho disponible"
            assert 200 < alto < 500, f"alto de gráfico fuera de rango: {alto}"

        # la tabla de trades scrollea sola; la página no
        overflow = page.evaluate(
            """() => Array.from(document.querySelectorAll('.table-wrap'))
                .map(t => getComputedStyle(t).overflowX)"""
        )
        assert overflow and all(value == "auto" for value in overflow)

        # objetivos táctiles de 44 px
        alturas = page.evaluate(
            """() => Array.from(document.querySelectorAll('summary'))
                .map(s => s.getBoundingClientRect().height)"""
        )
        for altura in alturas:
            assert altura >= 44, f"objetivo táctil de {altura}px (mínimo 44)"

        # texto legible sin zoom
        tamano = page.evaluate(
            "parseFloat(getComputedStyle(document.body).fontSize)"
        )
        assert tamano >= 14
        browser.close()
