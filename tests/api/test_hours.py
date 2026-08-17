"""Endpoints de horários."""

from __future__ import annotations

import fakeredis
import fakeredis.aioredis
import httpx
import pytest
from fastapi import FastAPI

from src.config import Settings
from src.main import create_app
from src.services.calendar_service import TradingCalendar
from src.services.redis_service import RedisService
from tests.conftest import FakeClock, SpyRedis


async def test_hours(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/hours")
    assert r.status_code == 200
    assert r.json() == {"open": "10:00", "close": "18:00"}


async def test_hours_faz_um_unico_mget(
    settings: Settings,
    seeded_redis: fakeredis.aioredis.FakeRedis,
    clock: FakeClock,
    test_calendar: TradingCalendar,
    make_client: object,
) -> None:
    spy = SpyRedis(seeded_redis)
    app = create_app(settings)
    app.state.redis_service = RedisService(settings, client_factory=lambda: spy, now_fn=clock)
    app.state.calendar = test_calendar

    async with make_client(app) as c:  # type: ignore[operator]
        assert (await c.get("/v1/hours")).status_code == 200
    assert spy.calls["mget"] == 1
    assert spy.calls["get"] == 0


async def test_hours_open(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/hours/open")
    assert r.status_code == 200
    assert r.json() == {"time": "10:00"}


async def test_hours_close(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/hours/close")
    assert r.status_code == 200
    assert r.json() == {"time": "18:00"}


async def test_metodo_nao_permitido(client: httpx.AsyncClient) -> None:
    assert (await client.post("/v1/hours")).status_code == 405


async def test_503_sem_redis_e_sem_cache(
    settings: Settings,
    fake_server: fakeredis.FakeServer,
    clock: FakeClock,
    test_calendar: TradingCalendar,
    make_client: object,
) -> None:
    fake_server.connected = False
    cliente = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)
    app = create_app(settings)
    app.state.redis_service = RedisService(settings, client_factory=lambda: cliente, now_fn=clock)
    app.state.calendar = test_calendar

    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/hours")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["error"] == "Service Unavailable"
    assert "cache local" in detail["message"]
    assert detail["key"]


async def test_404_quando_a_chave_nao_existe(
    settings: Settings,
    fake_redis: fakeredis.aioredis.FakeRedis,
    clock: FakeClock,
    test_calendar: TradingCalendar,
    make_client: object,
) -> None:
    """Regressão: com o Redis no ar e a chave ausente, a resposta era 503
    "Redis indisponível" — uma afirmação falsa."""
    app = create_app(settings)
    app.state.redis_service = RedisService(
        settings, client_factory=lambda: fake_redis, now_fn=clock
    )
    app.state.calendar = test_calendar

    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/hours")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["error"] == "Not Found"
    assert detail["key"] == settings.redis_key_open


async def test_503_com_cache_expirado_informa_a_idade(
    client: httpx.AsyncClient, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    assert (await client.get("/v1/hours")).status_code == 200

    fake_server.connected = False
    clock.advance(3601)
    r = await client.get("/v1/hours")
    assert r.status_code == 503
    assert r.json()["detail"]["cache_age_seconds"] == 3601


async def test_degradado_serve_do_cache(
    client: httpx.AsyncClient, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    assert (await client.get("/v1/hours")).status_code == 200

    fake_server.connected = False
    clock.advance(60)
    r = await client.get("/v1/hours")
    assert r.status_code == 200
    assert r.json() == {"open": "10:00", "close": "18:00"}


@pytest.mark.parametrize("valor", ["25:00", "abc", "10:60", "1000"])
async def test_valor_invalido_no_redis_nao_e_servido_como_200(
    settings: Settings,
    fake_redis: fakeredis.aioredis.FakeRedis,
    clock: FakeClock,
    test_calendar: TradingCalendar,
    make_client: object,
    valor: str,
) -> None:
    """A documentação promete HH:MM, mas o Redis aceita qualquer string.

    502 e não 500: a falha é do upstream. Antes a exceção escapava sem tratamento.
    """
    await fake_redis.set(settings.redis_key_open, valor)
    await fake_redis.set(settings.redis_key_close, "18:00")
    app = create_app(settings)
    app.state.redis_service = RedisService(
        settings, client_factory=lambda: fake_redis, now_fn=clock
    )
    app.state.calendar = test_calendar

    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/hours")
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "Bad Gateway"


async def test_503_quando_o_servico_nao_foi_inicializado(
    settings: Settings, make_client: object
) -> None:
    app: FastAPI = create_app(settings)
    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/hours")
    assert r.status_code == 503
