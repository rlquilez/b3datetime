"""Contrato contra um Redis real.

O `fakeredis` cobre 100% do serviço, mas pode divergir do Redis real exatamente na
semântica que estas correções dependem: string vazia devolvida como `""` e não `None`,
e `decode_responses` entregando `str`. Estes quatro testes são a única defesa contra
esse drift. Eles dão skip automático quando não há Redis alcançável, então a suíte
continua verde localmente.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import redis.asyncio as aioredis
from redis.exceptions import RedisError

pytestmark = pytest.mark.integration

# db 15, nunca 0: o teardown faz flushdb.
REDIS_TEST_URL = "redis://localhost:6379/15"


@pytest.fixture
async def real_redis() -> AsyncIterator[aioredis.Redis]:
    client = aioredis.from_url(
        REDIS_TEST_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
    )
    try:
        await client.ping()
    except (RedisError, OSError):
        await client.aclose()
        pytest.skip("Redis não disponível em localhost:6379")
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


async def test_mget_devolve_str_e_nao_bytes(real_redis: aioredis.Redis) -> None:
    await real_redis.set("t:open", "10:00")
    await real_redis.set("t:close", "18:00")

    valores = await real_redis.mget(["t:open", "t:close"])
    assert valores == ["10:00", "18:00"]
    assert all(isinstance(v, str) for v in valores)


async def test_string_vazia_volta_como_string_vazia(real_redis: aioredis.Redis) -> None:
    """Valida a premissa do fakeredis que sustenta a correção do falso 503."""
    await real_redis.set("t:vazio", "")
    assert await real_redis.get("t:vazio") == ""
    assert await real_redis.get("t:vazio") is not None
    assert await real_redis.mget(["t:vazio"]) == [""]


async def test_chave_ausente_volta_none(real_redis: aioredis.Redis) -> None:
    assert await real_redis.get("t:nao-existe") is None
    assert await real_redis.mget(["t:nao-existe"]) == [None]


async def test_mget_parcial(real_redis: aioredis.Redis) -> None:
    await real_redis.set("t:existe", "v")
    assert await real_redis.mget(["t:existe", "t:nao-existe"]) == ["v", None]


async def test_conexao_em_porta_fechada_falha_rapido() -> None:
    client = aioredis.from_url(
        "redis://127.0.0.1:1", decode_responses=True, socket_connect_timeout=1
    )
    with pytest.raises((RedisError, OSError)):
        await client.ping()
    await client.aclose()
