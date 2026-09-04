"""Raiz da API: metadados e links cientes do prefixo do proxy.

No JSON os links são caminhos absolutos **com o prefixo**, lido de ``scope["root_path"]``
(``/<prefixo>/docs``). Antes eram ``/docs`` e ``./openapi.json``: atrás do Kong, o
primeiro apontava para fora do prefixo e o segundo, resolvido contra ``/<prefixo>``,
caía em ``/openapi.json`` (a RFC 3986 descarta o último segmento). As páginas HTML, ao
contrário, continuam com URLs relativas — o browser as resolve contra a URL pública.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.config import Settings
from src.config import settings as default_settings
from src.routers.openapi_examples import API_KEY_HEADER, TAG_ROOT, success_response

router = APIRouter(tags=[TAG_ROOT])

DESCRIPTION = "API para consultar horários e dias de operação da B3"
MANAGED_BY = "Kong Gateway"

ROOT_EXAMPLE = {
    "name": default_settings.api_title,
    "version": default_settings.api_version,
    "description": DESCRIPTION,
    "docs": {"swagger": "/docs", "redoc": "/redoc", "openapi": "/openapi.json"},
    "endpoints": {
        "hours": {"all": "/v1/hours", "open": "/v1/hours/open", "close": "/v1/hours/close"},
        "dates": {
            "is_trading_day": "/v1/is-trading-day",
            "trading_days": "/v1/trading-days?start=YYYY-MM-DD&end=YYYY-MM-DD&exclude=false",
            "calendar_info": "/v1/calendar-info",
        },
        "health": "/v1/health",
    },
    "authentication": {"required": False, "type": None, "header": None, "managed_by": MANAGED_BY},
}


class DocsLinks(BaseModel):
    """Links da documentação interativa."""

    swagger: str = Field(..., description="Swagger UI", json_schema_extra={"example": "/docs"})
    redoc: str = Field(..., description="ReDoc", json_schema_extra={"example": "/redoc"})
    openapi: str = Field(
        ..., description="Schema OpenAPI em JSON", json_schema_extra={"example": "/openapi.json"}
    )


class HoursLinks(BaseModel):
    """Endpoints de horários de operação."""

    all: str = Field(
        ..., description="Abertura e fechamento", json_schema_extra={"example": "/v1/hours"}
    )
    open: str = Field(
        ..., description="Só a abertura", json_schema_extra={"example": "/v1/hours/open"}
    )
    close: str = Field(
        ..., description="Só o fechamento", json_schema_extra={"example": "/v1/hours/close"}
    )


class DatesLinks(BaseModel):
    """Endpoints de dias de negociação."""

    is_trading_day: str = Field(
        ...,
        description="Hoje é dia de negociação?",
        json_schema_extra={"example": "/v1/is-trading-day"},
    )
    trading_days: str = Field(
        ...,
        description="Modelo de URL com os parâmetros obrigatórios",
        json_schema_extra={
            "example": "/v1/trading-days?start=YYYY-MM-DD&end=YYYY-MM-DD&exclude=false"
        },
    )
    calendar_info: str = Field(
        ...,
        description="Janela coberta pelo calendário",
        json_schema_extra={"example": "/v1/calendar-info"},
    )


class EndpointLinks(BaseModel):
    """Todos os endpoints da API."""

    hours: HoursLinks
    dates: DatesLinks
    health: str = Field(
        ..., description="Health check", json_schema_extra={"example": "/v1/health"}
    )


class AuthInfo(BaseModel):
    """Forma de autenticação em vigor. Só informa; quem valida é o Kong."""

    required: bool = Field(..., description="Se as requisições precisam de credencial")
    type: str | None = Field(
        default=None,
        description="Tipo da credencial, quando exigida",
        json_schema_extra={"example": "API Key"},
    )
    header: str | None = Field(
        default=None,
        description="Header que carrega a credencial, quando exigida",
        json_schema_extra={"example": API_KEY_HEADER},
    )
    managed_by: str = Field(
        ..., description="Quem valida a credencial", json_schema_extra={"example": MANAGED_BY}
    )


class RootResponse(BaseModel):
    """Metadados da API. Os links incluem o prefixo do proxy quando há um."""

    name: str = Field(..., description="Nome da API")
    version: str = Field(..., description="Versão publicada (SemVer)")
    description: str = Field(..., description="Resumo do que a API faz")
    docs: DocsLinks
    endpoints: EndpointLinks
    authentication: AuthInfo


@router.get(
    "/",
    summary="Informações da API",
    description=(
        "Nome, versão, links para a documentação e para cada endpoint, e a forma de "
        "autenticação em vigor. Atrás de um proxy com prefixo os links já vêm prefixados "
        "(ex.: `/<prefixo>/docs`)."
    ),
    responses={200: success_response("Metadados obtidos", ROOT_EXAMPLE)},
)
async def root(request: Request) -> RootResponse:
    """Metadados, com os links resolvidos contra ``scope["root_path"]``."""
    settings: Settings = request.app.state.settings
    prefix: str = request.scope.get("root_path", "")

    if settings.api_key_required:
        auth = AuthInfo(required=True, type="API Key", header=API_KEY_HEADER, managed_by=MANAGED_BY)
    else:
        auth = AuthInfo(required=False, managed_by=MANAGED_BY)

    return RootResponse(
        name=settings.api_title,
        version=settings.api_version,
        description=DESCRIPTION,
        docs=DocsLinks(
            swagger=f"{prefix}/docs",
            redoc=f"{prefix}/redoc",
            openapi=f"{prefix}/openapi.json",
        ),
        endpoints=EndpointLinks(
            hours=HoursLinks(
                all=f"{prefix}/v1/hours",
                open=f"{prefix}/v1/hours/open",
                close=f"{prefix}/v1/hours/close",
            ),
            dates=DatesLinks(
                is_trading_day=f"{prefix}/v1/is-trading-day",
                trading_days=(
                    f"{prefix}/v1/trading-days?start=YYYY-MM-DD&end=YYYY-MM-DD&exclude=false"
                ),
                calendar_info=f"{prefix}/v1/calendar-info",
            ),
            health=f"{prefix}/v1/health",
        ),
        authentication=auth,
    )
