"""Dependências injetáveis dos routers.

Os serviços vivem em ``app.state``, populados pelo ``lifespan``, e não em variáveis de
módulo. Isso dá escopo por instância de aplicação: cada teste constrói o seu próprio
app com os seus próprios fakes, sem vazamento entre testes e sem monkeypatch de global.
``app.dependency_overrides`` continua funcionando por cima, quando for preciso
substituir a dependência inteira.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from b3datetime.config import Settings
from b3datetime.services.calendar_service import TradingCalendar
from b3datetime.services.redis_service import RedisService


def get_app_settings(request: Request) -> Settings:
    """Settings da aplicação que atende o request — as passadas a ``create_app``.

    Antes era o ``get_settings()`` global: uma app criada com ``max_range_days=10``
    ainda aplicava o valor do ambiente nos endpoints de data, e o ``.env`` local
    vazava para os testes.
    """
    settings: Settings = request.app.state.settings
    return settings


def get_redis_service(request: Request) -> RedisService:
    """Serviço de Redis da aplicação."""
    service: RedisService | None = getattr(request.app.state, "redis_service", None)
    if service is None:  # pragma: no cover - só ocorre se o lifespan não rodou
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Service Unavailable",
                "message": "Serviço de Redis não inicializado",
            },
        )
    return service


def get_calendar(request: Request) -> TradingCalendar:
    """Calendário de negociação da aplicação.

    Quando o calendário não pôde ser construído, o app sobe assim mesmo (para que
    `/v1/hours` e `/v1/health` sigam respondendo) e apenas os endpoints de data
    retornam 503.
    """
    calendar: TradingCalendar | None = getattr(request.app.state, "calendar", None)
    if calendar is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Service Unavailable",
                "message": "Calendário de negociação indisponível",
            },
        )
    return calendar


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RedisDep = Annotated[RedisService, Depends(get_redis_service)]
CalendarDep = Annotated[TradingCalendar, Depends(get_calendar)]
