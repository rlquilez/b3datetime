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
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from b3datetime.config import Settings, get_settings
from b3datetime.documentacao import pagina_redoc, pagina_swagger
from b3datetime.middleware import RootPathPrefixMiddleware
from b3datetime.routers import dates, health, hours, root
from b3datetime.routers.openapi_examples import (
    API_KEY_SCHEME,
    BAD_GATEWAY_MESSAGE,
    OPENAPI_TAGS,
    SECURITY_SCHEMES,
    auth_description,
)
from b3datetime.services.calendar_service import CalendarUnavailableError, build_bvmf_calendar
from b3datetime.services.redis_service import (
    InvalidUpstreamValueError,
    KeyNotFoundError,
    RedisService,
    RedisUnavailableError,
)
from b3datetime.static import STATIC_DIR

logger = logging.getLogger(__name__)

# Caminho relativo nas páginas HTML: o browser o resolve contra a URL pública, que é a
# única coisa que funciona qualquer que seja a configuração do proxy. (No JSON de
# `GET /` a regra é outra: caminhos absolutos com o prefixo — ver src/b3datetime/routers/root.py.)
OPENAPI_RELATIVE_URL = "./openapi.json"

EXTERNAL_DOCS = {
    "description": "README, guia de migração e CHANGELOG",
    "url": "https://github.com/rlquilez/b3datetime#readme",
}


class B3DateTimeAPI(FastAPI):
    """FastAPI cujo schema declara o esquema de segurança `apikey` quando ele é exigido.

    Só metadado: a chave é validada pelo Kong e a aplicação continua sem nenhum código
    de autenticação. Com ``API_KEY_REQUIRED=true`` o Swagger UI exibe "Authorize" e envia
    o header no "Try it out"; com ``false`` nada de segurança é declarado. O FastAPI
    cacheia o schema em ``openapi_schema``; a mutação abaixo é idempotente.
    """

    def openapi(self) -> dict[str, Any]:
        schema = super().openapi()
        schema["externalDocs"] = EXTERNAL_DOCS
        settings: Settings = self.state.settings
        if settings.api_key_required:
            # O schema sempre tem `components` (os modelos de resposta): sem setdefault
            # defensivo, cujo default nenhum teste conseguiria distinguir.
            schema["components"]["securitySchemes"] = SECURITY_SCHEMES
            schema["security"] = [{API_KEY_SCHEME: []}]
        return schema


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

    @app.exception_handler(InvalidUpstreamValueError)
    async def _invalid_upstream(_: Request, exc: InvalidUpstreamValueError) -> JSONResponse:
        # O valor lido do Redis não satisfaz o contrato da resposta ("25:00" onde se
        # promete HH:MM, bytes que não são UTF-8). 502, porque a falha é do upstream.
        # Só esta exceção vira 502: antes era qualquer pydantic.ValidationError, e um
        # bug interno aparecia como "valor inválido no Redis".
        logger.error("Valor inválido lido do Redis: %s", exc, exc_info=exc.__cause__)
        return JSONResponse(
            status_code=502,
            content={"detail": {"error": "Bad Gateway", "message": BAD_GATEWAY_MESSAGE}},
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

    app = B3DateTimeAPI(
        title=settings.api_title,
        description=f"{settings.api_description}\n\n{auth_description(settings.api_key_required)}",
        version=settings.api_version,
        root_path=settings.root_path.rstrip("/"),
        # Sem redirect de barra final: o Location era montado com o header Host recebido
        # do proxy e, atrás do Kong com preserve_host=false, apontava para o endereço
        # interno do upstream — destino inalcançável que ainda expunha IP e porta.
        redirect_slashes=False,
        docs_url=None,  # servido abaixo, com assets locais
        redoc_url=None,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        contact={"name": "Rodrigo Quilez", "url": "https://github.com/rlquilez/b3datetime"},
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    )
    app.state.settings = settings

    # Corrige o scope antes de qualquer coisa que leia `path` (router, Mount). Ver o
    # docstring de src/b3datetime/middleware.py. Registrado ANTES do CORS: o CORS precisa ser a
    # camada mais externa (Sonar python:S8414), e a ordem entre os dois é indiferente —
    # o CORS só olha método e headers.
    app.add_middleware(RootPathPrefixMiddleware)

    # allow_credentials fica desligado: combinado com allow_origins=["*"], o Starlette
    # passa a refletir o Origin do chamador, o que equivale a confiar em toda origem
    # com credenciais. Se houver autenticação, ela é o header `apikey`, validado no Kong.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # pragma: no mutate - default do Starlette, explícito pela decisão de segurança acima
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    _register_exception_handlers(app)

    app.mount("/static", StaticFiles(directory=STATIC_DIR))
    app.include_router(hours.router)
    app.include_router(dates.router)
    app.include_router(health.router)
    app.include_router(root.router)

    # Páginas próprias, e não as do FastAPI: as dele têm script e estilo inline, que a
    # CSP da borda bloqueia — o /docs ficou em branco em produção (#75).
    @app.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return HTMLResponse(
            pagina_swagger(f"{settings.api_title} - Swagger UI", OPENAPI_RELATIVE_URL)
        )

    @app.get("/redoc", include_in_schema=False)
    async def redoc_ui() -> HTMLResponse:
        return HTMLResponse(pagina_redoc(f"{settings.api_title} - ReDoc", OPENAPI_RELATIVE_URL))

    return app
