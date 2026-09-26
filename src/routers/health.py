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


# Limites de exemplo coerentes com o exemplo de /v1/calendar-info: a janela começa num
# domingo (2016-09-04) e a primeira *sessão* é a segunda-feira seguinte.
_CALENDAR_EXAMPLE: dict[str, Any] = {
    "available": True,
    "first_session": "2016-09-05",
    "last_session": "2027-09-03",
    "sessions_count": 2730,
}


def _example(
    summary: str,
    status_value: str,
    *,
    redis_connected: bool,
    cache_age: int | None,
    calendar: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Exemplo nomeado de resposta do health, sempre numa combinação que a API produz."""
    expired = cache_age is None
    return {
        "summary": summary,
        "value": {
            "status": status_value,
            "timestamp": "2026-09-04T10:30:00-03:00",
            "redis_status": "connected" if redis_connected else "disconnected",
            "cache": {
                "redis_connected": redis_connected,
                "open_cache_age_seconds": cache_age,
                "close_cache_age_seconds": cache_age,
                "open_cache_expired": expired,
                "close_cache_expired": expired,
                "cache_ttl_seconds": 3600,
            },
            "calendar": calendar if calendar is not None else _CALENDAR_EXAMPLE,
        },
    }


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
                "healthy": _example(
                    "Sistema saudável", STATUS_HEALTHY, redis_connected=True, cache_age=120
                ),
                "degraded": _example(
                    "Redis offline, cache local ainda válido",
                    STATUS_DEGRADED,
                    redis_connected=False,
                    cache_age=1800,
                ),
            },
        ),
        # O corpo do 503 é o mesmo HealthResponse do 200. Sem `model`, o schema não era
        # documentado e o único exemplo mostrava `calendar: {"available": true}` sem os
        # limites — combinação que a API nunca produz (#46).
        503: {
            "model": HealthResponse,
            **examples_response(
                "API não saudável",
                {
                    "redis_unavailable": _example(
                        "Redis offline e sem cache utilizável",
                        STATUS_UNHEALTHY,
                        redis_connected=False,
                        cache_age=None,
                    ),
                    "calendar_unavailable": _example(
                        "Calendário indisponível",
                        STATUS_UNHEALTHY,
                        redis_connected=True,
                        cache_age=5,
                        calendar={"available": False},
                    ),
                },
            ),
        },
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
        # Sessões, e não a janela. O health lia o antigo alias `bounds`, que era a
        # cobertura: quando a janela começa num feriado ou fim de semana, anunciava como
        # "primeira sessão" um dia sem pregão, contradizendo /v1/calendar-info (#46).
        first, last = calendar.first_session, calendar.last_session
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
