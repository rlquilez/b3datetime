"""Endpoints de horários de operação da B3."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.dependencies import RedisDep
from src.routers.openapi_examples import (
    AUTH_NOTE,
    RESPONSE_KEY_NOT_FOUND,
    RESPONSE_REDIS_UNAVAILABLE,
)

router = APIRouter(prefix="/v1/hours", tags=["Horários de Operação"])

# Os horários vêm do Redis, que aceita qualquer string. Sem validação, um valor
# inválido gravado por engano era servido como 200 apesar de a documentação prometer
# HH:MM. O pattern faz a resposta falhar de forma visível em vez de propagar lixo.
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"

_CACHE_NOTE = (
    "Os horários são obtidos do Redis e mantidos em cache local por até 1 hora. "
    "Se o Redis estiver indisponível por mais tempo que isso, a resposta é 503. "
    "Se o Redis estiver disponível mas a chave não existir, a resposta é 404."
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
        json_schema_extra={"example": "18:00"},
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
    description=f"""
    Retorna os horários de abertura e fechamento da B3.

    {_CACHE_NOTE}

    As duas chaves são lidas numa única operação atômica, de modo que a resposta nunca
    combina um horário de abertura antigo com um de fechamento novo.

    {AUTH_NOTE}
    """,
    responses={
        200: {
            "description": "Horários obtidos com sucesso",
            "content": {"application/json": {"example": {"open": "10:00", "close": "18:00"}}},
        },
        404: RESPONSE_KEY_NOT_FOUND,
        503: RESPONSE_REDIS_UNAVAILABLE,
    },
)
async def get_trading_hours(redis: RedisDep) -> TradingHours:
    """Horários de abertura e fechamento, num único MGET."""
    open_time, close_time = await redis.get_trading_hours()
    return TradingHours(open=open_time, close=close_time)


@router.get(
    "/open",
    summary="Obter horário de abertura",
    description=f"""
    Retorna apenas o horário de abertura da B3.

    {_CACHE_NOTE}

    {AUTH_NOTE}
    """,
    responses={
        200: {
            "description": "Horário de abertura obtido com sucesso",
            "content": {"application/json": {"example": {"time": "10:00"}}},
        },
        404: RESPONSE_KEY_NOT_FOUND,
        503: RESPONSE_REDIS_UNAVAILABLE,
    },
)
async def get_open_time(redis: RedisDep) -> TradingTime:
    """Horário de abertura."""
    return TradingTime(time=await redis.get_open_time())


@router.get(
    "/close",
    summary="Obter horário de fechamento",
    description=f"""
    Retorna apenas o horário de fechamento da B3.

    {_CACHE_NOTE}

    {AUTH_NOTE}
    """,
    responses={
        200: {
            "description": "Horário de fechamento obtido com sucesso",
            "content": {"application/json": {"example": {"time": "18:00"}}},
        },
        404: RESPONSE_KEY_NOT_FOUND,
        503: RESPONSE_REDIS_UNAVAILABLE,
    },
)
async def get_close_time(redis: RedisDep) -> TradingTime:
    """Horário de fechamento."""
    return TradingTime(time=await redis.get_close_time())
