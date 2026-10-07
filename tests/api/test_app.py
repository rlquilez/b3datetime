"""Raiz, documentação e CORS, em processo e sem I/O (o wiring real fica em tests/integration)."""

from __future__ import annotations

import httpx

from b3datetime.config import Settings
from b3datetime.static import REDOC_JS, SWAGGER_CSS, SWAGGER_JS


async def test_root(client: httpx.AsyncClient, settings: Settings) -> None:
    r = await client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == settings.api_title
    assert body["version"] == settings.api_version
    assert body["endpoints"]["health"] == "/v1/health"
    assert body["endpoints"]["dates"]["calendar_info"] == "/v1/calendar-info"
    assert set(body) == {"name", "version", "description", "docs", "endpoints", "authentication"}


async def test_root_sem_prefixo_usa_caminhos_absolutos(client: httpx.AsyncClient) -> None:
    """`docs.openapi` era `./openapi.json`: resolvido por um cliente contra `/<prefixo>`,
    caía em `/openapi.json`, fora do prefixo (a RFC 3986 descarta o último segmento).
    No JSON os links são absolutos; só as páginas HTML usam URLs relativas."""
    body = (await client.get("/")).json()
    assert body["docs"] == {"swagger": "/docs", "redoc": "/redoc", "openapi": "/openapi.json"}


async def test_docs_servido_sem_cdn(client: httpx.AsyncClient) -> None:
    """Regressão: /docs caía no cdn.jsdelivr.net default e /redoc carregava
    cdn.redoc.ly/.../latest sem SRI, apesar do docstring dizer "without CDN"."""
    r = await client.get("/docs")
    assert r.status_code == 200
    html = r.text
    assert SWAGGER_JS in html
    assert SWAGGER_CSS in html
    assert "cdn.jsdelivr.net" not in html
    assert "//" not in html.replace("./static", "").replace("<!DOCTYPE", "")


async def test_redoc_servido_sem_cdn(client: httpx.AsyncClient) -> None:
    r = await client.get("/redoc")
    assert r.status_code == 200
    html = r.text
    assert REDOC_JS in html
    assert "cdn.redoc.ly" not in html
    assert "fonts.googleapis.com" not in html


async def test_cors_sem_credenciais(client: httpx.AsyncClient) -> None:
    """Regressão: allow_origins=["*"] com allow_credentials=True fazia o Starlette
    refletir o Origin do chamador, equivalendo a confiar em toda origem."""
    r = await client.get("/v1/health", headers={"Origin": "https://malicioso.example"})
    assert r.headers.get("access-control-allow-credentials") != "true"


async def test_preflight_cors_permite_get(client: httpx.AsyncClient) -> None:
    r = await client.options(
        "/v1/health",
        headers={"Origin": "https://app.example", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "GET" in r.headers["access-control-allow-methods"]


async def test_preflight_cors_rejeita_post(client: httpx.AsyncClient) -> None:
    """A API é só leitura: o preflight de um POST é recusado."""
    r = await client.options(
        "/v1/health",
        headers={"Origin": "https://app.example", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 400


async def test_rota_desconhecida(client: httpx.AsyncClient) -> None:
    assert (await client.get("/nao-existe")).status_code == 404
