"""A aplicação inteira, em processo, com as dependências reais.

Lifespan real, Redis real (db 15) e o calendário BVMF real — o único ponto da suíte em
que o caminho completo request → dependência → serviço → Redis/calendário roda sem
nenhum dublê e sem container. O E2E faz o mesmo contra a imagem; aqui a falha aponta
direto para a linha, e a cobertura conta.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest
import redis.asyncio as aioredis
from asgi_lifespan import LifespanManager

from b3datetime.config import Settings
from b3datetime.main import create_app
from tests.integration.conftest import REDIS_TEST_URL

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture
async def cliente_real(real_redis: aioredis.Redis) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(_env_file=None, redis_url=REDIS_TEST_URL)
    await real_redis.set(settings.redis_key_open, "10:00")
    await real_redis.set(settings.redis_key_close, "17:00")
    app = create_app(settings)
    async with (
        LifespanManager(app, startup_timeout=180),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def test_horarios_vem_do_redis_real(cliente_real: httpx.AsyncClient) -> None:
    r = await cliente_real.get("/v1/hours")
    assert r.status_code == 200, r.text
    assert r.json() == {"open": "10:00", "close": "17:00"}
    assert (await cliente_real.get("/v1/hours/open")).json() == {"time": "10:00"}


async def test_health_saudavel_com_tudo_real(cliente_real: httpx.AsyncClient) -> None:
    r = await cliente_real.get("/v1/health")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["status"] == "healthy"
    assert corpo["redis_status"] == "connected"
    assert corpo["cache"]["redis_connected"] is True
    assert corpo["calendar"]["available"] is True


async def test_calendario_real_responde_pelos_endpoints(cliente_real: httpx.AsyncClient) -> None:
    info = (await cliente_real.get("/v1/calendar-info")).json()
    assert info["exchange"] == "BVMF"
    assert info["sessions_count"] > 2000  # ~10 anos de pregões

    hoje = (await cliente_real.get("/v1/is-trading-day")).json()
    assert date.fromisoformat(hoje["date"])
    assert isinstance(hoje["is_trading_day"], bool)


async def test_chave_apagada_no_redis_real_vira_404(
    cliente_real: httpx.AsyncClient, real_redis: aioredis.Redis
) -> None:
    await real_redis.delete(Settings(_env_file=None).redis_key_close)
    r = await cliente_real.get("/v1/hours/close")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "Not Found"
