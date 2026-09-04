"""Endpoints de horários de operação da B3."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.dependencies import RedisDep
from src.routers.openapi_examples import RESPONSES_HOURS_ERRORS, TAG_HOURS, success_response

router = APIRouter(prefix="/v1/hours", tags=[TAG_HOURS])

# Os horários vêm do Redis, que aceita qualquer string. Sem validação, um valor
# inválido gravado por engano era servido como 200 apesar de a documentação prometer
# HH:MM. O pattern faz a resposta falhar de forma visível em vez de propagar lixo.
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"

_CACHE_NOTE = (
    "Os horários são obtidos do Redis e mantidos em cache local por até 1 hora. "
    "Se o Redis estiver indisponível por mais tempo que isso, a resposta é 503. "
    "Se o Redis estiver disponível mas a chave não existir, a resposta é 404. "
    "Se o valor armazenado não estiver no formato `HH:MM`, a resposta é 502."
)


class TradingHours(BaseModel):
    """Horários de abertura e fechamento."""

    open: str = Field(
        ...,
        description="Horário de abertura no formato HH:MM",
        pattern=TIME_PATTERN,
        json_schema_extra={"example": "10:00"},
    )
    close: str = Field(
        ...,
        description="Horário de fechamento no formato HH:MM",
        pattern=TIME_PATTERN,
        json_schema_extra={"example": "17:00"},
    )


class TradingTime(BaseModel):
    """Horário único."""

    time: str = Field(
        ...,
        description="Horário no formato HH:MM",
        pattern=TIME_PATTERN,
        json_schema_extra={"example": "10:00"},
    )


@router.get(
    "",
    summary="Obter horários de abertura e fechamento",
    description=f"""Retorna os horários de abertura e fechamento da B3.

{_CACHE_NOTE}

As duas chaves são lidas numa única operação atômica, de modo que a resposta nunca
combina um horário de abertura antigo com um de fechamento novo.""",
    responses={
        200: success_response("Horários obtidos com sucesso", {"open": "10:00", "close": "17:00"}),
        **RESPONSES_HOURS_ERRORS,
    },
)
async def get_trading_hours(redis: RedisDep) -> TradingHours:
    """Horários de abertura e fechamento, num único MGET."""
    open_time, close_time = await redis.get_trading_hours()
    return TradingHours(open=open_time, close=close_time)


@router.get(
    "/open",
    summary="Obter horário de abertura",
    description=f"""Retorna apenas o horário de abertura da B3.

{_CACHE_NOTE}""",
    responses={
        200: success_response("Horário de abertura obtido com sucesso", {"time": "10:00"}),
        **RESPONSES_HOURS_ERRORS,
    },
)
async def get_open_time(redis: RedisDep) -> TradingTime:
    """Horário de abertura."""
    return TradingTime(time=await redis.get_open_time())


@router.get(
    "/close",
    summary="Obter horário de fechamento",
    description=f"""Retorna apenas o horário de fechamento da B3.

{_CACHE_NOTE}""",
    responses={
        200: success_response("Horário de fechamento obtido com sucesso", {"time": "17:00"}),
        **RESPONSES_HOURS_ERRORS,
    },
)
async def get_close_time(redis: RedisDep) -> TradingTime:
    """Horário de fechamento."""
    return TradingTime(time=await redis.get_close_time())
