"""Assets estáticos da documentação (Swagger UI, ReDoc e favicon)."""

from __future__ import annotations

import httpx
import pytest

from src.static import FAVICON, REDOC_JS, SWAGGER_CSS, SWAGGER_JS

# Python 3.11 reporta application/javascript; 3.12, text/javascript.
JS_TYPES = {"application/javascript", "text/javascript"}
CONTENT_TYPES = {
    SWAGGER_JS: JS_TYPES,
    SWAGGER_CSS: {"text/css"},
    REDOC_JS: JS_TYPES,
    FAVICON: {"image/png"},
}


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
    """Regressão: o mount apontava para o diretório do pacote src/static e servia o
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
