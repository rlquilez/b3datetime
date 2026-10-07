"""Fixtures da integração: dependências reais, em processo.

Este bloco é onde a suíte encontra o mundo real — Redis de verdade, o calendário BVMF
construído pelo ``exchange_calendars`` e o lifespan da aplicação. Os blocos ``unit`` e
``api`` ficam sem I/O; tudo o que abre socket ou constrói o calendário real mora aqui.

O Redis é o de ``localhost:6379``, **db 15** (o teardown faz ``flushdb``). Sem Redis
alcançável, os testes que dependem dele são pulados — e o job de integração do CI, que
sobe um Redis como service, reprova se qualquer teste for pulado.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import redis.asyncio as aioredis
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from redis.exceptions import RedisError

from b3datetime.config import Settings
from b3datetime.main import create_app

# db 15, nunca 0: o teardown faz flushdb.
REDIS_TEST_URL = "redis://localhost:6379/15"


@pytest.fixture
async def real_redis() -> AsyncIterator[aioredis.Redis]:
    client = aioredis.from_url(
        REDIS_TEST_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
    )
    try:
        await client.ping()
    except RedisError, OSError:
        await client.aclose()
        pytest.skip("Redis não disponível em localhost:6379")
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def lifespan_app(settings: Settings) -> AsyncIterator[FastAPI]:
    """App com o lifespan real executado: calendário BVMF real e tentativa real no Redis."""
    application = create_app(settings)
    async with LifespanManager(application, startup_timeout=180):
        yield application
