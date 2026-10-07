"""Documentação publicada: as páginas, o schema e tudo o que o navegador busca a partir delas.

Os assets são resolvidos contra a URL da página, como o navegador faz. Foi assim que a
documentação ficou em branco em produção enquanto a suíte seguia verde: a página
respondia, mas ``/static/*`` não (ver ``tests/api/test_proxy_prefix.py``).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import pytest

from tests.e2e.conftest import Ambiente

pytestmark = pytest.mark.e2e

PAGINAS = {"swagger": "/docs", "redoc": "/redoc"}
SCHEMA = "/openapi.json"

# href/src/spec-url="..." no HTML e url: '...' no JS de inicialização do Swagger UI.
REFERENCIA = re.compile(r"""(?:href|src|spec-url)="([^"]+)"|url:\s*'([^']+)'""")
TIPOS = {
    ".css": "text/css",
    ".js": "text/javascript",
    ".png": "image/png",
    ".json": "application/json",
}


@pytest.mark.parametrize("pagina", sorted(PAGINAS.values()))
def test_pagina_e_todos_os_assets_respondem(principal: Ambiente, pagina: str) -> None:
    r = principal.http.get(pagina)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")

    referencias = [a or b for a, b in REFERENCIA.findall(r.text)]
    assert referencias, f"{pagina} não referencia nenhum asset"
    externas = [ref for ref in referencias if re.match(r"(?:https?:)?//", ref)]
    assert not externas, f"{pagina} depende de recurso externo (CDN): {externas}"

    for ref in referencias:
        url = urljoin(str(r.url), ref)
        asset = principal.http.get(url)
        assert asset.status_code == 200, f"{pagina} -> {url}: {asset.status_code}"
        extensao = "." + url.rsplit(".", 1)[-1]
        assert asset.headers["content-type"].startswith(TIPOS[extensao]), (url, asset.headers)


def test_schema_publicado(principal: Ambiente) -> None:
    r = principal.http.get(SCHEMA)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    schema = r.json()
    assert schema["openapi"].startswith("3.1")
    assert schema["info"]["title"] == "B3 DateTime API"
    assert schema["paths"]


def test_toda_documentacao_anunciada_e_testada(principal: Ambiente) -> None:
    """``GET /`` anuncia a documentação; tudo o que ele anuncia está nesta suíte."""
    docs = principal.http.get("/").json()["docs"]
    p = principal.prefixo
    cobertos = {nome: p + caminho for nome, caminho in PAGINAS.items()} | {"openapi": p + SCHEMA}
    assert docs == cobertos
