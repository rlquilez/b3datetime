"""Fixtures compartilhadas.

Duas armadilhas que motivam o desenho abaixo:

* **Relógio.** ``RedisCache`` chama ``datetime.now`` através de uma função injetada.
  Um monkeypatch em ``src.config.get_current_datetime`` passaria batido, porque a
  referência é capturada na construção. Por isso o relógio é injetado, não remendado.
* **`.env` local.** ``Settings(_env_file=None)`` é obrigatório: sem isso, um ``.env``
  na máquina do desenvolvedor muda o resultado da suíte.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import fakeredis.aioredis
import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from src.config import Settings
from src.main import create_app
from src.services.calendar_service import TradingCalendar
from src.services.redis_service import RedisService
from tests.factories import make_calendar

TZ = ZoneInfo("America/Sao_Paulo")


class FakeClock:
    """Relógio controlável, com fuso igual ao da aplicação."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 15, 10, 30, tzinfo=TZ)

    def __call__(self) -> datetime:
        return self._now

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class SpyRedis:
    """Encapsula um cliente fake contando as chamadas, para provar o MGET único."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: dict[str, int] = {"mget": 0, "get": 0, "ping": 0}

    async def mget(self, keys: list[str]) -> list[str | None]:
        self.calls["mget"] += 1
        return await self._inner.mget(keys)

    async def get(self, key: str) -> str | None:
        self.calls["get"] += 1
        return await self._inner.get(key)

    async def ping(self) -> bool:
        self.calls["ping"] += 1
        return await self._inner.ping()

    async def aclose(self) -> None:
        await self._inner.aclose()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings() -> Settings:
    # _env_file=None isola a suíte de um .env local.
    return Settings(_env_file=None)


@pytest.fixture
def fake_server() -> fakeredis.FakeServer:
    """Servidor fake; alterne ``.connected`` para simular queda e retorno do Redis."""
    return fakeredis.FakeServer()


@pytest.fixture
async def fake_redis(
    fake_server: fakeredis.FakeServer,
) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def seeded_redis(
    fake_redis: fakeredis.aioredis.FakeRedis, settings: Settings
) -> fakeredis.aioredis.FakeRedis:
    await fake_redis.set(settings.redis_key_open, "10:00")
    await fake_redis.set(settings.redis_key_close, "18:00")
    return fake_redis


@pytest.fixture
def redis_service(
    settings: Settings, seeded_redis: fakeredis.aioredis.FakeRedis, clock: FakeClock
) -> RedisService:
    return RedisService(settings, client_factory=lambda: seeded_redis, now_fn=clock)


@pytest.fixture
def empty_redis_service(
    settings: Settings, fake_redis: fakeredis.aioredis.FakeRedis, clock: FakeClock
) -> RedisService:
    """Serviço apontando para um Redis no ar mas sem as chaves semeadas."""
    return RedisService(settings, client_factory=lambda: fake_redis, now_fn=clock)


@pytest.fixture(scope="session")
def test_calendar() -> TradingCalendar:
    """Calendário sintético de 2024. Não constrói nada do exchange_calendars."""
    return make_calendar()


@pytest.fixture
def app(settings: Settings, redis_service: RedisService, test_calendar: TradingCalendar) -> FastAPI:
    """App com o estado já populado — sem lifespan, portanto sem I/O."""
    application = create_app(settings)
    application.state.redis_service = redis_service
    application.state.calendar = test_calendar
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def make_client() -> Any:
    """Fábrica de clientes para testes que precisam customizar o estado do app."""

    def _factory(application: FastAPI) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        )

    return _factory


@pytest.fixture
async def lifespan_app(settings: Settings) -> AsyncIterator[FastAPI]:
    """App com o lifespan real executado — usado só nos testes de wiring."""
    application = create_app(settings)
    async with LifespanManager(application, startup_timeout=180):
        yield application


@pytest.fixture
def today_session(test_calendar: TradingCalendar) -> date:
    """Uma data que é sessão dentro do calendário de teste."""
    return date(2024, 1, 15)
