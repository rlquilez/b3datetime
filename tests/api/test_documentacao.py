"""As páginas de documentação não têm script nem estilo inline (#75).

A borda envia ``Content-Security-Policy: script-src 'self'; style-src 'self'``. Com o
``<script>`` inline do ``get_swagger_ui_html`` do FastAPI, o ``/docs`` ficou em branco em
produção, e o ``<style>`` do ``get_redoc_html`` era bloqueado no ``/redoc``. Aqui fica a
regra estática: nada inline nas duas páginas. Que elas de fato **renderizam** sob a CSP
quem prova é o teste em navegador, ``tests/e2e/test_documentacao_no_navegador.py``.
"""

from __future__ import annotations

from html.parser import HTMLParser

import httpx
import pytest

from b3datetime.documentacao import pagina_redoc, pagina_swagger

SWAGGER_ESPERADO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>B3 DateTime API - Swagger UI</title>
<link rel="stylesheet" href="./static/swagger-ui.css">
<link rel="icon" href="./static/favicon.png">
</head>
<body>
<div id="swagger-ui" data-openapi-url="./openapi.json"></div>
<script src="./static/swagger-ui-bundle.js"></script>
<script src="./static/swagger-init.js"></script>
</body>
</html>
"""

REDOC_ESPERADO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>B3 DateTime API - ReDoc</title>
<link rel="stylesheet" href="./static/documentacao.css">
<link rel="icon" href="./static/favicon.png">
</head>
<body>
<noscript>O ReDoc precisa de JavaScript para exibir a documentação.</noscript>
<redoc spec-url="./openapi.json" disable-search="true"></redoc>
<script src="./static/redoc.standalone.js"></script>
</body>
</html>
"""


class _Inline(HTMLParser):
    """Coleta tudo o que uma CSP sem ``'unsafe-inline'`` bloquearia."""

    def __init__(self) -> None:
        super().__init__()
        self.violacoes: list[str] = []
        self._dentro_de: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        nomes = {nome for nome, _ in attrs}
        if tag == "script" and "src" not in nomes:
            self.violacoes.append("<script> sem src")
        if tag == "style":
            self.violacoes.append("<style>")
        self.violacoes += [
            f"atributo {n} em <{tag}>" for n in sorted(nomes) if n == "style" or n.startswith("on")
        ]
        self.violacoes += [
            f"URL javascript: em <{tag}>"
            for _, v in attrs
            if (v or "").lower().startswith("javascript:")
        ]
        self._dentro_de = tag if tag == "script" else None

    def handle_data(self, data: str) -> None:
        if self._dentro_de == "script" and data.strip():
            self.violacoes.append("<script> com corpo")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._dentro_de = None


def _inline(html: str) -> list[str]:
    parser = _Inline()
    parser.feed(html)
    return parser.violacoes


@pytest.mark.parametrize("pagina", ["/docs", "/redoc"])
async def test_paginas_sem_script_nem_estilo_inline(client: httpx.AsyncClient, pagina: str) -> None:
    r = await client.get(pagina)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert _inline(r.text) == []


async def test_docs_e_a_pagina_esperada(client: httpx.AsyncClient) -> None:
    r = await client.get("/docs")
    assert r.text == SWAGGER_ESPERADO


async def test_redoc_e_a_pagina_esperada_sem_busca(client: httpx.AsyncClient) -> None:
    """``disable-search``: a busca do ReDoc cria um worker a partir de ``blob:``, que
    ``script-src 'self'`` bloqueia."""
    r = await client.get("/redoc")
    assert r.text == REDOC_ESPERADO


def test_o_detector_pega_o_que_o_fastapi_gerava() -> None:
    """Sem isto, um detector quebrado aprovaria qualquer página."""
    fastapi_swagger = (
        '<script src="./b.js"></script><script>const ui = SwaggerUIBundle({})</script>'
    )
    assert _inline(fastapi_swagger) == ["<script> sem src", "<script> com corpo"]
    assert _inline("<style>body { margin: 0 }</style>") == ["<style>"]
    assert sorted(_inline('<div style="x" onclick="y"><a href="javascript:z">')) == [
        "URL javascript: em <a>",
        "atributo onclick em <div>",
        "atributo style em <div>",
    ]
    assert _inline('<script src="./b.js"></script><p>texto</p>') == []


def test_titulo_e_url_sao_escapados() -> None:
    html = pagina_swagger('<script>"x"</script>', './a"b.json')
    assert "<title>&lt;script&gt;&quot;x&quot;&lt;/script&gt;</title>" in html
    assert 'data-openapi-url="./a&quot;b.json"' in html
    assert "<title>&lt;b&gt;</title>" in pagina_redoc("<b>", "./c.json")
    assert 'spec-url="./a&quot;b.json"' in pagina_redoc("t", './a"b.json')
