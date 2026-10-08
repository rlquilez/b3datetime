"""Assets estáticos da documentação (Swagger UI, ReDoc e favicon)."""

from __future__ import annotations

import httpx
import pytest

from b3datetime.static import (
    DOCS_CSS,
    FAVICON,
    REDOC_JS,
    REDOC_VERSION,
    STATIC_DIR,
    SWAGGER_CSS,
    SWAGGER_INIT_JS,
    SWAGGER_JS,
    SWAGGER_UI_VERSION,
)

# O mimetypes do Python >= 3.12 (o projeto só roda 3.14) usa text/javascript.
JS_TYPES = {"text/javascript"}
CONTENT_TYPES = {
    SWAGGER_JS: JS_TYPES,
    SWAGGER_CSS: {"text/css"},
    REDOC_JS: JS_TYPES,
    FAVICON: {"image/png"},
}


# Os assets do próprio projeto, que tiraram o script e o estilo inline das páginas (#75).
# Pequenos por natureza: ficam fora do `> 1000 bytes`, que protege os vendorizados de um
# download truncado; o que se confere é o conteúdo que a página depende.
PROPRIOS = {
    SWAGGER_INIT_JS: (JS_TYPES, "SwaggerUIBundle("),
    DOCS_CSS: ({"text/css"}, "margin: 0"),
}


@pytest.mark.parametrize("asset", sorted(PROPRIOS))
async def test_assets_proprios_das_paginas(client: httpx.AsyncClient, asset: str) -> None:
    tipos, trecho = PROPRIOS[asset]
    r = await client.get(f"/static/{asset}")
    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0] in tipos
    assert trecho in r.text


def test_inicializacao_do_swagger_le_o_contrato_do_atributo_da_pagina() -> None:
    """O JS e a página combinam pelo atributo: renomear um lado sem o outro deixaria o
    Swagger UI sem contrato — e só o teste de navegador perceberia."""
    js = (STATIC_DIR / SWAGGER_INIT_JS).read_text(encoding="utf-8")
    assert 'getElementById("swagger-ui")' in js
    assert 'getAttribute("data-openapi-url")' in js


@pytest.mark.parametrize("asset", sorted(CONTENT_TYPES))
async def test_asset_existe_com_content_type(client: httpx.AsyncClient, asset: str) -> None:
    r = await client.get(f"/static/{asset}")
    assert r.status_code == 200
    assert len(r.content) > 1000
    assert r.headers["content-type"].split(";")[0] in CONTENT_TYPES[asset]


@pytest.mark.parametrize("asset", sorted(CONTENT_TYPES))
async def test_head_responde_sem_corpo(client: httpx.AsyncClient, asset: str) -> None:
    get = await client.get(f"/static/{asset}")
    head = await client.head(f"/static/{asset}")
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(get.content))


async def test_asset_desconhecido_e_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/static/nao-existe.css")).status_code == 404


async def test_static_nao_serve_o_pacote(client: httpx.AsyncClient) -> None:
    """Regressão: o mount apontava para o diretório do pacote b3datetime/static e servia o
    __init__.py como text/x-python."""
    assert (await client.get("/static/__init__.py")).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/static/%2e%2e/config.py",
        "/static/..%2fconfig.py",
        "/static/%2e%2e/%2e%2e/pyproject.toml",
    ],
)
async def test_traversal_nao_escapa_do_diretorio(client: httpx.AsyncClient, path: str) -> None:
    """O httpx normaliza `..` literal no cliente; só as formas codificadas chegam ao
    StaticFiles, e nenhuma pode sair do diretório de assets."""
    r = await client.get(path)
    assert r.status_code == 404
    assert "api_version" not in r.text


def test_versoes_declaradas_batem_com_os_assets_vendorizados() -> None:
    """``SWAGGER_UI_VERSION``/``REDOC_VERSION`` documentam o que está em ``assets/``; atualizar
    um arquivo sem a constante (ou o contrário) deixa a versão anunciada mentindo — e é por
    ela que se acompanha CVE de biblioteca JS vendorizada, que nem Dependabot nem Trivy veem."""
    assert SWAGGER_UI_VERSION in (STATIC_DIR / SWAGGER_JS).read_text(encoding="utf-8")
    assert f'"{REDOC_VERSION}"' in (STATIC_DIR / REDOC_JS).read_text(encoding="utf-8")
