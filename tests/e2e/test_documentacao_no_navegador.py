"""A documentação RENDERIZA num navegador real, sob a CSP da borda (#75).

Duas vezes o ``/docs`` ficou em branco em produção com a suíte verde. Na primeira, os
assets davam 404 atrás do Kong (``root_path``). Na segunda, a CSP do Cloudflare
(``script-src 'self'; style-src 'self'``) bloqueou o script inline do Swagger UI e os
estilos injetados pelo ReDoc. Os testes conferiam que cada página e cada asset respondiam
200; nenhum abria a página. Este abre, no Chromium:

* **contra a imagem** (``E2E_IMAGE``): a CSP da borda é **injetada** em toda resposta. A
  documentação precisa sobreviver a ela *antes* de ser publicada;
* **contra a produção** (``E2E_BASE_URL``, no job de pós-deploy): sem injeção — valem os
  headers que a borda envia de verdade.

Renderizar é: o título do contrato na página e **toda operação do contrato** visível,
sem erro de JavaScript, sem erro de console e sem violação de CSP.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import Ambiente
from tests.e2e.contrato import Contrato

if TYPE_CHECKING:
    from playwright.sync_api import Browser, ConsoleMessage, Page, Route

# Sem wheel para musl: no `docker run python:3.14-alpine` documentado, o módulo é pulado.
# No CI ele está instalado (requirements-browser.txt) e o job de E2E reprova qualquer pulo.
sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

# A CSP que a borda envia nas páginas de documentação (regra do Cloudflare, ver
# tests/README.md, seção Produção). Sem 'unsafe-inline' em scripts: as páginas não têm
# script inline desde #75. O upgrade-insecure-requests fica de fora — só importa em HTTPS.
CSP_DO_DOCS = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'"
)
# O ReDoc injeta estilos em tempo de execução (styled-components): é o mínimo a mais que
# /redoc exige. A busca dele (worker a partir de blob:) está desligada na página.
CSP_DO_REDOC = CSP_DO_DOCS.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
CSP_POR_PAGINA = {"/docs": CSP_DO_DOCS, "/redoc": CSP_DO_REDOC}

# Violações aceitas, cada uma com motivo — bloquear é o desejado, nada de terceiros:
TOLERADOS = (
    # o logo de atribuição do ReDoc vem de cdn.redoc.ly, fixo no bundle e sem opção para
    # desligar; o componente se esconde sozinho quando a imagem falha;
    "https://cdn.redoc.ly/redoc/logo-mini.svg",
    # o beacon do Cloudflare Web Analytics, que a borda injeta nas páginas HTML e a própria
    # CSP da borda bloqueia (só em produção).
    "https://static.cloudflareinsights.com/beacon.min.js",
)
TEMPO_LIMITE_MS = 20_000


@pytest.fixture(scope="module")
def navegador() -> Iterator[Browser]:
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


def _registrar_erros(page: Page) -> list[str]:
    erros: list[str] = []

    def no_console(mensagem: ConsoleMessage) -> None:
        if mensagem.type == "error":
            erros.append(mensagem.text)

    page.on("console", no_console)
    page.on("pageerror", lambda erro: erros.append(f"pageerror: {erro}"))
    return erros


def _abrir(navegador: Browser, principal: Ambiente, pagina: str) -> tuple[Page, list[str]]:
    """Abre a página e devolve-a com os erros que o navegador registrou."""
    page = navegador.new_page()
    erros = _registrar_erros(page)
    if principal.container is not None:
        csp = CSP_POR_PAGINA[pagina]

        def injetar(route: Route) -> None:
            resposta = route.fetch()
            headers = {**resposta.headers, "content-security-policy": csp}
            route.fulfill(response=resposta, headers=headers)

        page.route("**/*", injetar)
    url = str(principal.http.build_request("GET", pagina).url)
    page.goto(url, wait_until="networkidle", timeout=TEMPO_LIMITE_MS)
    return page, erros


def _sem_erros(erros: list[str]) -> list[str]:
    return [e for e in erros if not any(t in e for t in TOLERADOS)]


def test_swagger_ui_renderiza_todas_as_operacoes(
    navegador: Browser, principal: Ambiente, contrato: Contrato
) -> None:
    page, erros = _abrir(navegador, principal, "/docs")
    try:
        titulo = page.locator(".swagger-ui .info .title")
        titulo.wait_for(timeout=TEMPO_LIMITE_MS)
        assert contrato.documento["info"]["title"] in titulo.inner_text()
        caminhos = {caminho for _, caminho in contrato.operacoes()}
        for caminho in caminhos:
            seletor = f'.opblock-summary-path[data-path="{caminho}"]'
            assert page.locator(seletor).count() == 1, f"{caminho} não aparece no /docs"
        assert page.locator(".opblock").count() == len(contrato.operacoes())
        assert _sem_erros(erros) == []
    finally:
        page.close()


def test_try_it_out_do_swagger_executa_uma_chamada_real(
    navegador: Browser, principal: Ambiente
) -> None:
    """Renderizar não basta: o "Try it out" faz a chamada pela página, sob o connect-src
    da CSP e com o prefixo de `servers`. É um GET de leitura — seguro em produção."""
    page, erros = _abrir(navegador, principal, "/docs")
    try:
        page.locator('.opblock-summary-path[data-path="/v1/hours"]').click()
        page.locator("button.try-out__btn").first.click()
        page.locator("button.execute").first.click()
        status = page.locator(".live-responses-table tbody .response-col_status").first
        status.wait_for(timeout=TEMPO_LIMITE_MS)
        assert status.inner_text().strip() == "200"
        corpo = page.locator(".live-responses-table .microlight").first.inner_text()
        assert '"open"' in corpo
        assert '"close"' in corpo
        assert _sem_erros(erros) == []
    finally:
        page.close()


def test_redoc_renderiza_todas_as_operacoes(
    navegador: Browser, principal: Ambiente, contrato: Contrato
) -> None:
    page, erros = _abrir(navegador, principal, "/redoc")
    try:
        titulo = page.locator("h1").first
        titulo.wait_for(timeout=TEMPO_LIMITE_MS)
        assert contrato.documento["info"]["title"] in titulo.inner_text()
        for caminho, item in contrato.documento["paths"].items():
            for operacao in item.values():
                seletor = f'[data-section-id$="/operation/{operacao["operationId"]}"]'
                assert page.locator(seletor).count() >= 1, f"{caminho} não aparece no /redoc"
        assert _sem_erros(erros) == []
    finally:
        page.close()


def test_a_csp_injetada_reprovaria_a_pagina_antiga(navegador: Browser, principal: Ambiente) -> None:
    """Prova de que a injeção funciona: o HTML que o FastAPI gerava (script inline) é
    bloqueado pela CSP do /docs. Só no modo imagem — em produção não há o que injetar."""
    if principal.container is None:
        pytest.skip("só contra a imagem: em produção a CSP é a da borda, não injetada")
    page = navegador.new_page()
    erros = _registrar_erros(page)
    antiga = '<!DOCTYPE html><div id="x"></div><script>document.getElementById("x").textContent = "ok"</script>'

    def servir(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="text/html",
            body=antiga,
            headers={"content-security-policy": CSP_DO_DOCS},
        )

    url = str(principal.http.build_request("GET", "/pagina-antiga").url)
    page.route(url, servir)
    page.goto(url)
    try:
        assert page.locator("#x").inner_text() == ""
        assert any("inline script" in e for e in erros), erros
    finally:
        page.close()
