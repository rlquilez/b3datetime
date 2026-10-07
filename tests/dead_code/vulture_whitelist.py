"""Whitelist do vulture: o que o framework usa e a análise estática não enxerga.

Nunca é importado nem executado — o vulture só o lê como código-fonte, e cada nome
mencionado aqui conta como "usado". Por isso cada entrada é uma referência ao símbolo
real (o mypy confere que ele existe), agrupada pelo motivo de o vulture não a ver.

Handlers registrados por decorador (``@router.get``, ``@app.get``,
``@app.exception_handler``) não estão aqui: o ``[tool.vulture] ignore_decorators`` os
cobre. Um nome novo só entra nesta lista depois de alguém confirmar que ele é usado
fora do alcance do vulture; código morto de verdade se apaga.
"""

from __future__ import annotations

from fastapi import Response

from b3datetime import main
from b3datetime.config import Settings
from b3datetime.routers import dates, health, hours, root

# O uvicorn chama a factory pelo nome (`b3datetime.main:create_app --factory`), e o
# pydantic-settings lê `model_config` da classe.
CHAMADOS_PELO_NOME = (main.create_app, Settings.model_config)

# Campos de modelos de resposta: preenchidos por keyword (ou `model_validate`) e lidos
# pela serialização do FastAPI — nenhum código os lê como atributo.
CAMPOS_DE_RESPOSTA = (
    dates.TradingDayResponse.is_trading_day,
    dates.CalendarInfoResponse.exchange,
    dates.CalendarInfoResponse.sessions_count,
    health.CacheStatus.open_cache_age_seconds,
    health.CacheStatus.close_cache_age_seconds,
    health.CacheStatus.open_cache_expired,
    health.CacheStatus.close_cache_expired,
    health.CalendarStatus.available,
    health.CalendarStatus.sessions_count,
    health.HealthResponse.timestamp,
    health.HealthResponse.redis_status,
    hours.TradingHours.open,
    hours.TradingHours.close,
    root.DocsLinks.swagger,
    root.DocsLinks.redoc,
    root.HoursLinks.all,
    root.HoursLinks.open,
    root.HoursLinks.close,
    root.DatesLinks.is_trading_day,
    root.DatesLinks.trading_days,
    root.DatesLinks.calendar_info,
    root.AuthInfo.required,
    root.AuthInfo.type,
    root.AuthInfo.header,
    root.AuthInfo.managed_by,
    root.RootResponse.name,
    root.RootResponse.version,
    root.RootResponse.docs,
    root.RootResponse.endpoints,
    root.RootResponse.authentication,
)


def lido_pelo_framework(resposta: Response) -> int:
    """Atribuído no Response injetado pelo FastAPI (/v1/health devolve 503 quando unhealthy)."""
    return resposta.status_code


# Exportados: o vulture conta nomes em `__all__` como usados.
__all__ = ["CAMPOS_DE_RESPOSTA", "CHAMADOS_PELO_NOME", "lido_pelo_framework"]
