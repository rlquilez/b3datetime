"""O corpo exato das respostas de erro e dos cabeçalhos de CORS.

Os outros testes de componente conferem status e trechos de mensagem. Estes conferem o
envelope **inteiro**: é o que o cliente recebe e o que a documentação exemplifica. Também
é o que o teste de mutação exige — uma mensagem trocada por ``"XX…XX"`` ou em caixa alta
passava em qualquer teste que só procurasse um trecho.
"""

from __future__ import annotations

import fakeredis
import fakeredis.aioredis
import httpx
from freezegun import freeze_time

from b3datetime.config import Settings
from b3datetime.main import create_app
from b3datetime.services.calendar_service import TradingCalendar
from b3datetime.services.redis_service import RedisService
from tests.conftest import FakeClock
from tests.factories import make_empty_calendar

FORA_DA_JANELA_2024 = (
    "Período fora da janela coberta pelo calendário (2024-01-01 a 2024-12-31). "
    "Consulte GET /v1/calendar-info para os limites vigentes."
)
INDISPONIVEL = "Service Unavailable"


async def test_periodo_invertido(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/trading-days", params={"start": "2024-01-10", "end": "2024-01-02"})
    assert r.status_code == 400
    assert r.json() == {
        "detail": {
            "error": "Bad Request",
            "message": "A data final deve ser maior ou igual à data inicial",
        }
    }


async def test_periodo_acima_do_limite(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/trading-days", params={"start": "2000-01-01", "end": "2030-01-01"})
    assert r.status_code == 400
    assert r.json()["detail"] == {
        "error": "Bad Request",
        "message": "O período pedido tem 10958 dias e excede o máximo de 3660 dias por requisição",
    }


async def test_periodo_fora_da_janela(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/trading-days", params={"start": "2023-12-01", "end": "2024-01-10"})
    assert r.status_code == 400
    assert r.json()["detail"] == {"error": "Bad Request", "message": FORA_DA_JANELA_2024}


@freeze_time("2010-06-15 13:30:00")
async def test_hoje_fora_da_janela(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/is-trading-day")
    assert r.status_code == 503
    assert r.json()["detail"] == {"error": INDISPONIVEL, "message": FORA_DA_JANELA_2024}


async def test_calendario_vazio(
    settings: Settings, redis_service: RedisService, make_client: object
) -> None:
    app = create_app(settings)
    app.state.redis_service = redis_service
    app.state.calendar = make_empty_calendar()
    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/calendar-info")
    assert r.status_code == 503
    assert r.json()["detail"] == {"error": INDISPONIVEL, "message": "Calendário vazio"}


async def test_calendario_nao_construido(
    settings: Settings, redis_service: RedisService, make_client: object
) -> None:
    """Sem o atributo no ``app.state`` (o lifespan não chegou a defini-lo), e não só ``None``."""
    app = create_app(settings)
    app.state.redis_service = redis_service
    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/calendar-info")
    assert r.status_code == 503
    assert r.json()["detail"] == {
        "error": INDISPONIVEL,
        "message": "Calendário de negociação indisponível",
    }


async def test_servico_de_redis_nao_inicializado(
    settings: Settings, test_calendar: TradingCalendar, make_client: object
) -> None:
    app = create_app(settings)
    app.state.calendar = test_calendar
    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/hours")
    assert r.status_code == 503
    assert r.json()["detail"] == {
        "error": INDISPONIVEL,
        "message": "Serviço de Redis não inicializado",
    }


async def test_redis_fora_sem_cache(
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
        r = await c.get("/v1/hours/open")
    assert r.status_code == 503
    assert r.json()["detail"] == {
        "error": INDISPONIVEL,
        "message": "Redis indisponível e nenhum valor em cache local",
        "key": settings.redis_key_open,
    }


async def test_redis_fora_com_cache_vencido(
    client: httpx.AsyncClient,
    settings: Settings,
    fake_server: fakeredis.FakeServer,
    clock: FakeClock,
) -> None:
    assert (await client.get("/v1/hours/close")).status_code == 200
    fake_server.connected = False
    clock.advance(3601)
    r = await client.get("/v1/hours/close")
    assert r.status_code == 503
    assert r.json()["detail"] == {
        "error": INDISPONIVEL,
        "message": "Redis indisponível há mais de 3600s",
        "key": settings.redis_key_close,
        "cache_age_seconds": 3601,
    }


async def test_cache_com_idade_igual_ao_ttl_ainda_serve(
    client: httpx.AsyncClient, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    """Fronteira do TTL: estrito (``>``). Com a idade exatamente igual, o cache serve."""
    assert (await client.get("/v1/hours")).status_code == 200
    fake_server.connected = False
    clock.advance(3600)
    r = await client.get("/v1/hours")
    assert r.status_code == 200
    assert r.json() == {"open": "10:00", "close": "18:00"}


async def test_chave_ausente(
    settings: Settings,
    fake_redis: fakeredis.aioredis.FakeRedis,
    clock: FakeClock,
    test_calendar: TradingCalendar,
    make_client: object,
) -> None:
    await fake_redis.set(settings.redis_key_open, "10:00")
    app = create_app(settings)
    app.state.redis_service = RedisService(
        settings, client_factory=lambda: fake_redis, now_fn=clock
    )
    app.state.calendar = test_calendar
    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/hours")
    assert r.status_code == 404
    assert r.json() == {
        "detail": {
            "error": "Not Found",
            "message": "Chave não encontrada no Redis",
            "key": settings.redis_key_close,
        }
    }


async def test_preflight_permite_qualquer_cabecalho_e_anuncia_os_metodos(
    client: httpx.AsyncClient,
) -> None:
    """``allow_headers=["*"]``: um preflight com cabeçalho próprio é aceito, e a resposta
    anuncia exatamente os métodos que a API serve."""
    r = await client.options(
        "/v1/hours",
        headers={
            "Origin": "https://app.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Cliente, Accept-Language",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-methods"] == "GET, OPTIONS"
    assert r.headers["access-control-allow-headers"].lower() == "x-cliente, accept-language"
    assert "access-control-allow-credentials" not in r.headers
