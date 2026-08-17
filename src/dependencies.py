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

from src.config import Settings, get_settings
from src.services.calendar_service import TradingCalendar
from src.services.redis_service import RedisService


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


SettingsDep = Annotated[Settings, Depends(get_settings)]
RedisDep = Annotated[RedisService, Depends(get_redis_service)]
CalendarDep = Annotated[TradingCalendar, Depends(get_calendar)]
