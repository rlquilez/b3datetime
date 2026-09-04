"""Endpoint de health check.

O ponto central destes testes é o **código HTTP**, não só o corpo: enquanto os três
estados respondiam 200, o HEALTHCHECK do Dockerfile e as probes do Kubernetes não
tinham como detectar falha alguma.
"""

from __future__ import annotations

import fakeredis
import fakeredis.aioredis
import httpx

from src.config import Settings
from src.main import create_app
from src.services.calendar_service import TradingCalendar
from src.services.redis_service import RedisService
from tests.conftest import FakeClock


async def test_healthy(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["redis_status"] == "connected"
    assert body["calendar"]["available"] is True


async def test_degraded_com_cache_fresco(
    client: httpx.AsyncClient, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    await client.get("/v1/hours")  # popula o cache

    fake_server.connected = False
    clock.advance(60)
    r = await client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["redis_status"] == "disconnected"


async def test_unhealthy_responde_503(
    settings: Settings,
    fake_server: fakeredis.FakeServer,
    clock: FakeClock,
    test_calendar: TradingCalendar,
    make_client: object,
) -> None:
    """Regressão: respondia 200 com status="unhealthy".

    O HEALTHCHECK do Dockerfile usa urllib.request.urlopen, que só falha em não-2xx,
    então o container nunca podia ser marcado unhealthy.
    """
    fake_server.connected = False
    cliente = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)
    app = create_app(settings)
    app.state.redis_service = RedisService(settings, client_factory=lambda: cliente, now_fn=clock)
    app.state.calendar = test_calendar

    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/health")

    assert r.status_code == 503
    assert r.json()["status"] == "unhealthy"


async def test_cache_expirado_e_unhealthy_nao_degraded(
    client: httpx.AsyncClient, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    """Regressão: um cache de dez horas era reportado como degraded (servível)
    enquanto /v1/hours já respondia 503 para o mesmo estado."""
    await client.get("/v1/hours")

    fake_server.connected = False
    clock.advance(3601)

    saude = await client.get("/v1/health")
    horas = await client.get("/v1/hours")

    assert saude.json()["status"] == "unhealthy"
    assert saude.status_code == 503
    # Os dois endpoints precisam concordar sobre o mesmo estado.
    assert horas.status_code == 503


async def test_considera_as_duas_chaves(
    settings: Settings,
    fake_redis: fakeredis.aioredis.FakeRedis,
    fake_server: fakeredis.FakeServer,
    clock: FakeClock,
    test_calendar: TradingCalendar,
    make_client: object,
) -> None:
    """Regressão: só open_cache_age_seconds era inspecionado, nunca close_."""
    await fake_redis.set(settings.redis_key_open, "10:00")
    app = create_app(settings)
    app.state.redis_service = RedisService(
        settings, client_factory=lambda: fake_redis, now_fn=clock
    )
    app.state.calendar = test_calendar

    async with make_client(app) as c:  # type: ignore[operator]
        await c.get("/v1/hours/open")  # popula só a chave de abertura
        fake_server.connected = False
        clock.advance(60)
        r = await c.get("/v1/health")

    assert r.json()["status"] == "unhealthy"
    assert r.status_code == 503


async def test_idade_zero_nao_e_reportada_como_ausencia(client: httpx.AsyncClient) -> None:
    """Regressão: idade 0.0 virava None, e None era a sentinela de "sem cache"."""
    await client.get("/v1/hours")
    body = (await client.get("/v1/health")).json()

    assert body["cache"]["open_cache_age_seconds"] == 0
    assert body["cache"]["open_cache_age_seconds"] is not None
    assert body["status"] != "unhealthy"


async def test_calendario_indisponivel_e_unhealthy(
    settings: Settings, redis_service: RedisService, make_client: object
) -> None:
    """O app sobe sem calendário para não entrar em crash-loop; o health precisa
    tornar isso visível ao orquestrador."""
    app = create_app(settings)
    app.state.redis_service = redis_service
    app.state.calendar = None

    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/health")

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unhealthy"
    # Igualdade exata: o schema tipado de `calendar` (response_model_exclude_unset)
    # não pode acrescentar chaves nulas ao JSON que os clientes já conhecem.
    assert body["calendar"] == {"available": False}


async def test_corpo_traz_ttl_e_limites(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/health")).json()
    assert body["cache"]["cache_ttl_seconds"] == 3600
    assert set(body["cache"]) == {
        "redis_connected",
        "open_cache_age_seconds",
        "close_cache_age_seconds",
        "open_cache_expired",
        "close_cache_expired",
        "cache_ttl_seconds",
    }
    assert body["calendar"]["first_session"] == "2024-01-01"
    assert body["calendar"]["sessions_count"] > 240
    assert set(body["calendar"]) == {"available", "first_session", "last_session", "sessions_count"}


async def test_timestamp_com_fuso_de_sao_paulo(client: httpx.AsyncClient) -> None:
    ts = (await client.get("/v1/health")).json()["timestamp"]
    assert ts.endswith(("-03:00", "-02:00"))
