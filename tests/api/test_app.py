"""Raiz, documentação, OpenAPI e wiring do app."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from src.config import Settings
from src.main import create_app
from src.services.redis_service import RedisService
from src.static import REDOC_JS, SWAGGER_CSS, SWAGGER_JS


async def test_root(client: httpx.AsyncClient, settings: Settings) -> None:
    r = await client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == settings.api_version
    assert body["endpoints"]["health"] == "/v1/health"
    assert body["endpoints"]["dates"]["calendar_info"] == "/v1/calendar-info"


async def test_root_usa_caminho_relativo_para_openapi(client: httpx.AsyncClient) -> None:
    """Atrás do Kong com prefixo, um caminho absoluto quebra a documentação."""
    assert (await client.get("/")).json()["docs"]["openapi"] == "./openapi.json"


async def test_openapi(client: httpx.AsyncClient) -> None:
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["license"]["name"] == "MIT"
    for path in [
        "/v1/hours",
        "/v1/hours/open",
        "/v1/hours/close",
        "/v1/health",
        "/v1/is-trading-day",
        "/v1/trading-days",
        "/v1/calendar-info",
    ]:
        assert path in schema["paths"], f"{path} ausente no schema"


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


@pytest.mark.parametrize("asset", [SWAGGER_JS, SWAGGER_CSS, REDOC_JS, "favicon.png"])
async def test_assets_estaticos_existem(client: httpx.AsyncClient, asset: str) -> None:
    r = await client.get(f"/static/{asset}")
    assert r.status_code == 200
    assert len(r.content) > 1000


async def test_cors_sem_credenciais(client: httpx.AsyncClient) -> None:
    """Regressão: allow_origins=["*"] com allow_credentials=True fazia o Starlette
    refletir o Origin do chamador, equivalendo a confiar em toda origem."""
    r = await client.get("/v1/health", headers={"Origin": "https://malicioso.example"})
    assert r.headers.get("access-control-allow-credentials") != "true"


async def test_rota_desconhecida(client: httpx.AsyncClient) -> None:
    assert (await client.get("/nao-existe")).status_code == 404


async def test_root_path_normalizado(settings: Settings) -> None:
    """ROOT_PATH com barra final produzia caminhos com barra dupla."""
    app = create_app(settings.model_copy(update={"root_path": "/b3datetime/"}))
    assert app.root_path == "/b3datetime"


# --- wiring do lifespan ---------------------------------------------------


async def test_lifespan_popula_o_estado(lifespan_app: FastAPI) -> None:
    assert lifespan_app.state.redis_service is not None
    assert lifespan_app.state.calendar is not None


async def test_app_sobe_com_calendario_quebrado(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, make_client: object
) -> None:
    """Regressão: a falha do calendário levantava RuntimeError em tempo de import,
    antes de o uvicorn abrir a porta — sem health endpoint e em crash-loop."""
    import src.main as main_mod
    from src.services.calendar_service import CalendarUnavailableError

    def boom(*_a: object, **_k: object) -> None:
        raise CalendarUnavailableError("catálogo indisponível")

    monkeypatch.setattr(main_mod, "build_bvmf_calendar", boom)

    app = create_app(settings)
    async with LifespanManager(app, startup_timeout=60):
        assert app.state.calendar is None
        async with make_client(app) as c:  # type: ignore[operator]
            # A API segue de pé, e o health torna a falha visível.
            assert (await c.get("/v1/health")).status_code == 503
            assert (await c.get("/")).status_code == 200


async def test_app_sobe_com_redis_fora(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.main as main_mod

    async def falha(self: RedisService) -> None:
        return None

    monkeypatch.setattr(main_mod.RedisService, "connect", falha)
    app = create_app(settings)
    async with LifespanManager(app, startup_timeout=180):
        assert app.state.redis_service is not None


@pytest.mark.slow
def test_import_nao_faz_io() -> None:
    """Regressão: o import conectava no Redis e construía dez anos de calendário.

    Rodado em subprocesso, com o Redis apontando para uma porta fechada: é a única
    verificação real de que nenhum I/O voltou para o tempo de import.
    """
    codigo = textwrap.dedent("""
        import time
        t = time.time()
        import src.main
        assert src.main.app is not None
        elapsed = time.time() - t
        assert elapsed < 3, f"import levou {elapsed:.2f}s; parece haver I/O"
    """)
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", codigo],
        env={"REDIS_URL_ENV": "redis://127.0.0.1:1", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
