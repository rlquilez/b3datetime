"""Cada diagrama renderizado como o GitHub renderiza, nos dois modos de cor, e medido.

O mermaid.js na versão do GitHub, com o ``initialize`` dele, no Chromium, sobre os fundos
do iframe (``#ffffff`` e ``#0d1117``). Reprova: erro de render, rótulo cortado ou fora da
forma, tag visível, nós sobrepostos, texto abaixo de 4,5:1 contra a superfície realmente
pintada, linha abaixo de 3:1 contra o fundo e texto encolhido abaixo do corpo mínimo.
As capturas vão para ``$DIAGRAMAS_CAPTURAS`` quando definido (o CI publica como artefato).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.docs.diagramas import Diagrama, diagramas
from tests.docs.renderizador import FUNDOS, LARGURA, MERMAID_JS, medir

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.diagramas
sync_api = pytest.importorskip("playwright.sync_api")

TODOS = diagramas()
CAPTURAS = os.environ.get("DIAGRAMAS_CAPTURAS")


@pytest.fixture(scope="module")
def pagina() -> Iterator[Page]:
    assert MERMAID_JS.is_file(), "rode `npm ci` em tests/docs (o mermaid.js do GitHub)"
    with sync_api.sync_playwright() as playwright:
        navegador = playwright.chromium.launch()
        pagina = navegador.new_page(
            viewport={"width": LARGURA + 32, "height": 900}, device_scale_factor=2
        )
        yield pagina
        navegador.close()


@pytest.mark.parametrize("modo", list(FUNDOS))
@pytest.mark.parametrize("diagrama", TODOS, ids=[d.id for d in TODOS])
def test_render_fiel_ao_github(pagina: Page, diagrama: Diagrama, modo: str) -> None:
    medicao = medir(pagina, diagrama, modo, Path(CAPTURAS) if CAPTURAS else None)
    assert not medicao.falhas(), "\n".join(medicao.falhas())
    assert medicao.textos, "nenhum texto medido: o render saiu vazio"
