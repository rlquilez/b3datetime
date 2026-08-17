"""B3 DateTime API — horários e dias de operação da B3.

O import deste módulo não faz I/O. Os serviços são construídos no ``lifespan`` e ficam
em ``app.state``. Antes, o calendário era construído em tempo de import e uma falha
levantava ``RuntimeError`` **antes de o uvicorn abrir a porta**: não havia health
endpoint, nem degradação, nem traceback útil — o orquestrador via apenas crash-loop.
Agora uma falha do calendário é registrada e degradada, e ``/v1/health`` passa a
responder 503, que é o que mantém a falha visível.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import Settings, get_settings
from src.routers import dates, health, hours
from src.services.calendar_service import CalendarUnavailableError, build_bvmf_calendar
from src.services.redis_service import KeyNotFoundError, RedisService, RedisUnavailableError
from src.static import REDOC_JS, STATIC_DIR, SWAGGER_CSS, SWAGGER_JS

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configura o logging raiz. Chamado no entrypoint, não no import."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Constrói e libera os serviços da aplicação."""
    settings: Settings = app.state.settings
    logger.info("Iniciando B3 DateTime API v%s", settings.api_version)
    logger.info("Timezone: %s | Exchange: %s", settings.timezone, settings.exchange_name)
    # URL redigida: o formato documentado inclui credenciais, e logá-la crua escrevia a
    # senha em texto puro no stdout e no agregador de logs.
    logger.info("Redis: %s | Cache TTL: %ds", settings.redis_url_safe, settings.cache_ttl_seconds)

    app.state.redis_service = RedisService(settings)
    await app.state.redis_service.connect()

    app.state.calendar = None
    try:
        # to_thread: a construção do calendário leva segundos e bloquearia o event loop.
        app.state.calendar = await asyncio.to_thread(build_bvmf_calendar, settings)
    except CalendarUnavailableError:
        logger.exception("Calendário indisponível; endpoints de datas responderão 503")

    try:
        yield
    finally:
        await app.state.redis_service.aclose()
        logger.info("Encerrando B3 DateTime API")


def _register_exception_handlers(app: FastAPI) -> None:
    """Traduz as exceções de domínio do serviço de Redis em respostas HTTP."""

    @app.exception_handler(KeyNotFoundError)
    async def _key_not_found(_: Request, exc: KeyNotFoundError) -> JSONResponse:
        # 404, e não 503: o Redis está no ar e apenas falta um SET. Colapsar os dois
        # casos mandava o operador depurar rede e DNS por engano.
        return JSONResponse(
            status_code=404,
            content={
                "detail": {
                    "error": "Not Found",
                    "message": "Chave não encontrada no Redis",
                    "key": exc.key,
                }
            },
        )

    @app.exception_handler(RedisUnavailableError)
    async def _redis_unavailable(_: Request, exc: RedisUnavailableError) -> JSONResponse:
        detail: dict[str, object] = {
            "error": "Service Unavailable",
            "message": str(exc),
            "key": exc.key,
        }
        if exc.cache_age is not None:
            detail["cache_age_seconds"] = int(exc.cache_age)
        return JSONResponse(status_code=503, content={"detail": detail})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Constrói a aplicação. Não executa I/O — isso é papel do ``lifespan``."""
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.api_title,
        description=settings.api_description,
        version=settings.api_version,
        root_path=settings.root_path.rstrip("/"),
        docs_url=None,  # servido abaixo, com assets locais
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
        contact={"name": "B3 DateTime API", "url": "https://github.com/rlquilez/b3datetime"},
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    )
    app.state.settings = settings

    # allow_credentials fica desligado: combinado com allow_origins=["*"], o Starlette
    # passa a refletir o Origin do chamador, o que equivale a confiar em toda origem
    # com credenciais. A autenticação desta API é o header `apikey`, validado no Kong.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    _register_exception_handlers(app)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(hours.router)
    app.include_router(dates.router)
    app.include_router(health.router)

    # Caminhos relativos: atrás do Kong com prefixo, um caminho absoluto para
    # openapi.json quebra a página de documentação.
    @app.get("/docs", include_in_schema=False)
    async def swagger_ui() -> object:
        return get_swagger_ui_html(
            openapi_url="./openapi.json",
            title=f"{settings.api_title} - Swagger UI",
            swagger_js_url=f"./static/{SWAGGER_JS}",
            swagger_css_url=f"./static/{SWAGGER_CSS}",
            swagger_favicon_url="./static/favicon.png",
        )

    @app.get("/redoc", include_in_schema=False)
    async def redoc_ui() -> object:
        return get_redoc_html(
            openapi_url="./openapi.json",
            title=f"{settings.api_title} - ReDoc",
            redoc_js_url=f"./static/{REDOC_JS}",
            redoc_favicon_url="./static/favicon.png",
            with_google_fonts=False,
        )

    @app.get("/", tags=["Root"], summary="Informações da API")
    async def root() -> dict[str, object]:
        return {
            "name": settings.api_title,
            "version": settings.api_version,
            "description": "API para consultar horários e dias de operação da B3",
            "docs": {
                "swagger": "/docs",
                "redoc": "/redoc",
                "openapi": "./openapi.json",
            },
            "endpoints": {
                "hours": {
                    "all": "/v1/hours",
                    "open": "/v1/hours/open",
                    "close": "/v1/hours/close",
                },
                "dates": {
                    "is_trading_day": "/v1/is-trading-day",
                    "trading_days": "/v1/trading-days?start=YYYY-MM-DD&end=YYYY-MM-DD&exclude=false",
                    "calendar_info": "/v1/calendar-info",
                },
                "health": "/v1/health",
            },
            "authentication": {
                "type": "API Key",
                "header": "apikey",
                "managed_by": "Kong Gateway",
            },
        }

    return app


app = create_app()
