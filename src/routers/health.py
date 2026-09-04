"""Endpoint de health check.

O estado ``unhealthy`` responde com **HTTP 503**, não 200. O HEALTHCHECK do Dockerfile
usa ``urllib.request.urlopen``, que só falha em status não-2xx; enquanto os três
estados respondiam 200, o container nunca podia ser marcado unhealthy — e o mesmo valia
para uma probe ``httpGet`` do Kubernetes. O health check era decorativo.

A avaliação também considera a expiração do cache. Antes, um cache de dez horas era
reportado como ``degraded`` (que a própria documentação descreve como servível)
enquanto ``/v1/hours`` já respondia 503 para o mesmo estado: os dois endpoints
afirmavam coisas contraditórias.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from src.config import get_current_datetime
from src.dependencies import RedisDep, SettingsDep
from src.routers.openapi_examples import TAG_HEALTH, examples_response

router = APIRouter(prefix="/v1", tags=[TAG_HEALTH])

STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_UNHEALTHY = "unhealthy"


class CacheStatus(BaseModel):
    """Estado do cache local dos horários."""

    redis_connected: bool = Field(..., description="Ping ao Redis bem-sucedido nesta verificação")
    open_cache_age_seconds: int | None = Field(
        ..., description="Idade do cache da abertura, em segundos; null se nunca populado"
    )
    close_cache_age_seconds: int | None = Field(
        ..., description="Idade do cache do fechamento, em segundos; null se nunca populado"
    )
    open_cache_expired: bool = Field(
        ..., description="Cache da abertura ausente ou mais velho que o TTL"
    )
    close_cache_expired: bool = Field(
        ..., description="Cache do fechamento ausente ou mais velho que o TTL"
    )
    cache_ttl_seconds: int = Field(..., description="TTL configurado (CACHE_TTL_SECONDS)")


class CalendarStatus(BaseModel):
    """Estado do calendário de negociação. Os limites só aparecem quando ele existe."""

    available: bool = Field(..., description="Calendário construído no arranque")
    first_session: str | None = Field(default=None, description="Primeira sessão carregada")
    last_session: str | None = Field(default=None, description="Última sessão carregada")
    sessions_count: int | None = Field(default=None, description="Quantidade de sessões carregadas")


class HealthResponse(BaseModel):
    """Estado da API e de suas dependências."""

    status: str = Field(
        ...,
        description="Estado geral da API: healthy, degraded ou unhealthy",
        json_schema_extra={"example": STATUS_HEALTHY},
    )
    timestamp: str = Field(
        ...,
        description="Momento da verificação, em ISO 8601",
        json_schema_extra={"example": "2026-09-04T10:30:00-03:00"},
    )
    redis_status: str = Field(
        ...,
        description="Estado da conexão com o Redis: connected ou disconnected",
        json_schema_extra={"example": "connected"},
    )
    cache: CacheStatus = Field(..., description="Estado do cache local")
    calendar: CalendarStatus = Field(..., description="Estado do calendário de negociação")


def _evaluate(cache: dict[str, Any], calendar_available: bool) -> str:
    """Deriva o estado geral a partir do Redis, do cache e do calendário."""
    if not calendar_available:
        # Sem calendário, metade da API não responde. O app sobe assim mesmo para não
        # entrar em crash-loop, mas precisa ser visível para o orquestrador.
        return STATUS_UNHEALTHY

    if cache["redis_connected"]:
        return STATUS_HEALTHY

    # Redis fora: só é degradado se ambas as chaves têm cache ainda válido. Um cache
    # expirado não serve — /v1/hours responderia 503.
    usable = (
        cache["open_cache_age_seconds"] is not None
        and cache["close_cache_age_seconds"] is not None
        and not cache["open_cache_expired"]
        and not cache["close_cache_expired"]
    )
    return STATUS_DEGRADED if usable else STATUS_UNHEALTHY


@router.get(
    "/health",
    summary="Verificar saúde da API",
    description="""Retorna o estado da API e de suas dependências.

**Estados e códigos HTTP**
- `healthy` (200): Redis conectado e calendário carregado
- `degraded` (200): Redis desconectado, mas ambas as chaves têm cache local válido
- `unhealthy` (**503**): sem cache utilizável, ou cache expirado, ou calendário
  indisponível

O 503 em `unhealthy` é o que permite ao Docker HEALTHCHECK e a probes do Kubernetes
detectarem a falha.""",
    # exclude_unset: sem calendário, `calendar` continua sendo só {"available": false},
    # exatamente como antes de o campo ganhar um schema tipado.
    response_model_exclude_unset=True,
    responses={
        200: examples_response(
            "API saudável ou degradada",
            {
                "healthy": {
                    "summary": "Sistema saudável",
                    "value": {
                        "status": STATUS_HEALTHY,
                        "timestamp": "2026-09-04T10:30:00-03:00",
                        "redis_status": "connected",
                        "cache": {
                            "redis_connected": True,
                            "open_cache_age_seconds": 120,
                            "close_cache_age_seconds": 120,
                            "open_cache_expired": False,
                            "close_cache_expired": False,
                            "cache_ttl_seconds": 3600,
                        },
                        "calendar": {
                            "available": True,
                            "first_session": "2016-09-04",
                            "last_session": "2027-09-03",
                            "sessions_count": 2730,
                        },
                    },
                },
                "degraded": {
                    "summary": "Redis offline, cache local ainda válido",
                    "value": {
                        "status": STATUS_DEGRADED,
                        "timestamp": "2026-09-04T10:30:00-03:00",
                        "redis_status": "disconnected",
                        "cache": {
                            "redis_connected": False,
                            "open_cache_age_seconds": 1800,
                            "close_cache_age_seconds": 1800,
                            "open_cache_expired": False,
                            "close_cache_expired": False,
                            "cache_ttl_seconds": 3600,
                        },
                        "calendar": {
                            "available": True,
                            "first_session": "2016-09-04",
                            "last_session": "2027-09-03",
                            "sessions_count": 2730,
                        },
                    },
                },
            },
        ),
        503: examples_response(
            "API não saudável",
            {
                "unhealthy": {
                    "summary": "Redis offline e sem cache utilizável",
                    "value": {
                        "status": STATUS_UNHEALTHY,
                        "timestamp": "2026-09-04T10:30:00-03:00",
                        "redis_status": "disconnected",
                        "cache": {
                            "redis_connected": False,
                            "open_cache_age_seconds": None,
                            "close_cache_age_seconds": None,
                            "open_cache_expired": True,
                            "close_cache_expired": True,
                            "cache_ttl_seconds": 3600,
                        },
                        "calendar": {"available": True},
                    },
                }
            },
        ),
    },
)
async def health_check(
    request: Request, response: Response, redis: RedisDep, settings: SettingsDep
) -> HealthResponse:
    """Estado da API e de suas dependências."""
    cache_status = await redis.get_cache_status()

    calendar = getattr(request.app.state, "calendar", None)
    calendar_status = CalendarStatus(available=False)
    if calendar is not None:
        first, last = calendar.bounds
        calendar_status = CalendarStatus(
            available=True,
            first_session=first.isoformat() if first else None,
            last_session=last.isoformat() if last else None,
            sessions_count=len(calendar),
        )

    overall = _evaluate(cache_status, calendar is not None)
    if overall == STATUS_UNHEALTHY:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall,
        timestamp=get_current_datetime(settings.tz).isoformat(),
        redis_status="connected" if cache_status["redis_connected"] else "disconnected",
        cache=CacheStatus.model_validate(cache_status),
        calendar=calendar_status,
    )
