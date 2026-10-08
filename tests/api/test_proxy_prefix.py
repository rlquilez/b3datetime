"""Páginas, assets e endpoints atrás de um proxy com prefixo (Kong).

O Kong remove o prefixo de ``path`` (``strip_path: true``) enquanto ``ROOT_PATH`` o
mantém em ``root_path``. O contrato ASGI exige que ``path`` comece com ``root_path``, e o
Starlette >= 0.35 depende disso para casar rotas montadas: sem a recomposição feita pelo
``RootPathPrefixMiddleware``, ``/static/*`` respondia 404 e a documentação ficava em
branco em produção — enquanto a suíte, que só testava sem prefixo, seguia verde.

Os testes rodam nos três modos de ``proxy_mode``: sem proxy, Kong com ``strip_path: true``
e Kong com ``strip_path: false``.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx
import pytest

from b3datetime.config import Settings
from b3datetime.services.calendar_service import TradingCalendar
from b3datetime.services.redis_service import RedisService
from b3datetime.static import (
    DOCS_CSS,
    FAVICON,
    REDOC_JS,
    SWAGGER_CSS,
    SWAGGER_INIT_JS,
    SWAGGER_JS,
)
from tests.conftest import PREFIX, ProxyMode, build_app

ASSETS = [SWAGGER_JS, SWAGGER_CSS, SWAGGER_INIT_JS, REDOC_JS, DOCS_CSS, FAVICON]
PAGES = ["/docs", "/redoc"]
ENDPOINTS = ["/", "/openapi.json", "/v1/hours", "/v1/hours/open", "/v1/calendar-info", "/v1/health"]

# Todo atributo que o navegador (ou o JS de inicialização) resolve contra a URL da página.
# A URL do contrato do Swagger UI está em data-openapi-url desde que a inicialização saiu
# do HTML (#75); antes era um `url: '...'` no script inline.
ASSET_REF = re.compile(r'(?:href|src|spec-url|data-openapi-url)="([^"]+)"')
# O que cada página tem de referenciar: a lista exata, para uma referência sumida (como a
# do contrato quando o script inline saiu) reprovar em vez de deixar o teste mais fraco.
PAGE_REFS = {
    "/docs": {
        f"./static/{SWAGGER_CSS}",
        f"./static/{FAVICON}",
        "./openapi.json",
        f"./static/{SWAGGER_JS}",
        f"./static/{SWAGGER_INIT_JS}",
    },
    "/redoc": {
        f"./static/{DOCS_CSS}",
        f"./static/{FAVICON}",
        "./openapi.json",
        f"./static/{REDOC_JS}",
    },
}
CONTENT_TYPES = {
    ".css": {"text/css"},
    # O mimetypes do Python >= 3.12 (o projeto só roda 3.14) usa text/javascript.
    ".js": {"text/javascript"},
    ".png": {"image/png"},
    ".json": {"application/json"},
}
# Placeholder do endereço interno do upstream, como o Kong o envia no header Host.
UPSTREAM_HOST = "upstream-interno:8710"


def _client(app: object, root_path: str = "") -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, root_path=root_path)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.parametrize("asset", ASSETS)
async def test_static_atras_do_kong_com_strip_path_true(
    settings: Settings,
    redis_service: RedisService,
    test_calendar: TradingCalendar,
    asset: str,
) -> None:
    """Regressão: com ROOT_PATH definido e o prefixo removido pelo Kong, o Mount
    propagava root_path="/b3datetime/static" e o StaticFiles procurava
    static/<arquivo> dentro do diretório de assets — 404 em todos, docs em branco."""
    app = build_app(settings.model_copy(update={"root_path": PREFIX}), redis_service, test_calendar)
    async with _client(app) as c:
        r = await c.get(f"/static/{asset}")
    assert r.status_code == 200


@pytest.mark.parametrize("page", PAGES)
async def test_paginas_referenciam_assets_que_respondem(
    proxied_client: httpx.AsyncClient, proxy_mode: ProxyMode, page: str
) -> None:
    """Cada href/src/spec-url/data-openapi-url da página, resolvido como o browser resolve (contra a
    URL pública), precisa responder 200 pelo caminho que o Kong entrega ao app."""
    public_page = proxy_mode.root_path + page
    r = await proxied_client.get(proxy_mode.upstream(public_page))
    assert r.status_code == 200

    refs = ASSET_REF.findall(r.text)
    assert set(refs) == PAGE_REFS[page]
    for ref in refs:
        public_path = urlsplit(urljoin(f"http://test{public_page}", ref)).path
        assert public_path.startswith(proxy_mode.root_path + "/"), ref
        asset = await proxied_client.get(proxy_mode.upstream(public_path))
        assert asset.status_code == 200, f"{ref} -> {public_path}"
        media_type = asset.headers["content-type"].split(";")[0]
        assert media_type in CONTENT_TYPES[PurePosixPath(public_path).suffix]


@pytest.mark.parametrize("path", ENDPOINTS)
async def test_endpoints_respondem_em_todos_os_modos(
    proxied_client: httpx.AsyncClient, proxy_mode: ProxyMode, path: str
) -> None:
    """A documentação dizia que strip_path=false fazia tudo responder 404; os dois
    modos precisam funcionar."""
    r = await proxied_client.get(proxy_mode.upstream(proxy_mode.root_path + path))
    assert r.status_code == 200, path


async def test_openapi_servers_por_modo(
    proxied_client: httpx.AsyncClient, proxy_mode: ProxyMode
) -> None:
    """`servers` é o que faz o "Try it out" do Swagger apontar para /<prefixo>/v1/..."""
    r = await proxied_client.get(proxy_mode.upstream(proxy_mode.root_path + "/openapi.json"))
    schema = r.json()
    if proxy_mode.root_path:
        assert schema["servers"] == [{"url": proxy_mode.root_path}]
    else:
        assert "servers" not in schema


@pytest.mark.parametrize("page", ["/docs", "/redoc", "/v1/hours", "/v1/health"])
async def test_barra_final_nao_redireciona_para_host_interno(
    proxied_client: httpx.AsyncClient, proxy_mode: ProxyMode, page: str
) -> None:
    """Regressão: `/docs/` respondia 307 com Location montado a partir de `path` (sem o
    prefixo) e do header Host recebido — atrás do Kong, o endereço interno do upstream."""
    public_path = proxy_mode.root_path + page + "/"
    r = await proxied_client.get(proxy_mode.upstream(public_path), headers={"host": UPSTREAM_HOST})
    assert r.status_code == 404
    assert "location" not in r.headers


async def test_links_do_root_sao_prefixados(
    proxied_client: httpx.AsyncClient, proxy_mode: ProxyMode
) -> None:
    """Regressão: `GET /` devolvia `/docs` e `./openapi.json` mesmo atrás do prefixo —
    o primeiro apontava para fora dele e o segundo caía em `/openapi.json`."""
    rp = proxy_mode.root_path
    body = (await proxied_client.get(proxy_mode.upstream(rp + "/"))).json()
    assert body["docs"] == {
        "swagger": f"{rp}/docs",
        "redoc": f"{rp}/redoc",
        "openapi": f"{rp}/openapi.json",
    }
    assert body["endpoints"]["health"] == f"{rp}/v1/health"
    assert body["endpoints"]["hours"]["all"] == f"{rp}/v1/hours"
    assert body["endpoints"]["dates"]["calendar_info"] == f"{rp}/v1/calendar-info"


def _links(node: object) -> list[str]:
    """Todos os caminhos (strings começando com /) de uma estrutura aninhada."""
    if isinstance(node, str):
        return [node] if node.startswith("/") else []
    if isinstance(node, dict):
        return [link for value in node.values() for link in _links(value)]
    return []


async def test_nenhum_link_do_root_responde_404(
    proxied_client: httpx.AsyncClient, proxy_mode: ProxyMode
) -> None:
    """Cada link anunciado por `GET /` precisa existir pelo caminho que o Kong entrega."""
    body = (await proxied_client.get(proxy_mode.upstream(proxy_mode.root_path + "/"))).json()
    links = _links({"docs": body["docs"], "endpoints": body["endpoints"]})
    assert len(links) >= 9
    for link in links:
        path = link.split("?")[0]
        r = await proxied_client.get(proxy_mode.upstream(path))
        assert r.status_code != 404, link


async def test_root_path_fornecido_pelo_servidor(
    settings: Settings, redis_service: RedisService, test_calendar: TradingCalendar
) -> None:
    """`uvicorn --root-path` põe o prefixo em root_path e em path; nada é duplicado."""
    app = build_app(settings, redis_service, test_calendar)  # sem ROOT_PATH
    async with _client(app, root_path=PREFIX) as c:
        assert (await c.get(f"{PREFIX}/static/{SWAGGER_CSS}")).status_code == 200
        assert (await c.get(f"/static/{SWAGGER_CSS}")).status_code == 200
        assert (await c.get(f"{PREFIX}/openapi.json")).json()["servers"] == [{"url": PREFIX}]


async def test_root_path_com_barra_final_e_normalizado(
    settings: Settings, redis_service: RedisService, test_calendar: TradingCalendar
) -> None:
    """ROOT_PATH com barra final produzia caminhos com barra dupla."""
    prefixed = settings.model_copy(update={"root_path": PREFIX + "/"})
    app = build_app(prefixed, redis_service, test_calendar)
    assert app.root_path == PREFIX
    async with _client(app) as c:
        assert (await c.get(f"/static/{FAVICON}")).status_code == 200
        assert (await c.get("/openapi.json")).json()["servers"] == [{"url": PREFIX}]
