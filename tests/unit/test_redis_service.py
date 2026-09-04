"""Serviço de Redis: leitura, fallback, reconexão e diagnóstico."""

from __future__ import annotations

import asyncio

import fakeredis
import fakeredis.aioredis
import pytest

from src.config import Settings
from src.services.redis_service import (
    KeyNotFoundError,
    RedisService,
    RedisUnavailableError,
)
from tests.conftest import FakeClock, SpyRedis


async def test_get_trading_hours(redis_service: RedisService) -> None:
    assert await redis_service.get_trading_hours() == ("10:00", "18:00")


async def test_horarios_lidos_em_um_unico_mget(
    settings: Settings, seeded_redis: fakeredis.aioredis.FakeRedis, clock: FakeClock
) -> None:
    """Regressão: eram duas leituras sequenciais, não atômicas.

    Um escritor concorrente podia produzir uma resposta com o `open` de ontem e o
    `close` de hoje, além de dobrar a latência.
    """
    spy = SpyRedis(seeded_redis)
    service = RedisService(settings, client_factory=lambda: spy, now_fn=clock)

    assert await service.get_trading_hours() == ("10:00", "18:00")
    assert spy.calls["mget"] == 1
    assert spy.calls["get"] == 0


async def test_leitura_popula_o_cache_das_duas_chaves(
    redis_service: RedisService, settings: Settings
) -> None:
    await redis_service.get_trading_hours()
    assert redis_service.local_cache.get_value(settings.redis_key_open) == "10:00"
    assert redis_service.local_cache.get_value(settings.redis_key_close) == "18:00"


async def test_string_vazia_nao_vira_503(
    settings: Settings, fake_redis: fakeredis.aioredis.FakeRedis, clock: FakeClock
) -> None:
    """Regressão: `if value:` fazia um Redis saudável com valor "" responder 503."""
    await fake_redis.set(settings.redis_key_open, "")
    await fake_redis.set(settings.redis_key_close, "18:00")
    service = RedisService(settings, client_factory=lambda: fake_redis, now_fn=clock)

    open_time, close_time = await service.get_trading_hours()
    assert open_time == ""
    assert close_time == "18:00"


async def test_chave_ausente_com_redis_no_ar_e_404(empty_redis_service: RedisService) -> None:
    """Regressão: respondia 503 "Redis indisponível" com o Redis perfeitamente no ar.

    Isso mandava o operador depurar rede e DNS quando a correção era um único SET.
    """
    with pytest.raises(KeyNotFoundError) as exc:
        await empty_redis_service.get_trading_hours()
    assert exc.value.key


async def test_chave_ausente_identifica_a_chave_que_falta(
    settings: Settings, fake_redis: fakeredis.aioredis.FakeRedis, clock: FakeClock
) -> None:
    await fake_redis.set(settings.redis_key_open, "10:00")
    service = RedisService(settings, client_factory=lambda: fake_redis, now_fn=clock)

    with pytest.raises(KeyNotFoundError) as exc:
        await service.get_trading_hours()
    assert exc.value.key == settings.redis_key_close


async def test_redis_fora_usa_cache_fresco(
    redis_service: RedisService, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    await redis_service.get_trading_hours()

    fake_server.connected = False
    clock.advance(60)
    assert await redis_service.get_trading_hours() == ("10:00", "18:00")


async def test_redis_fora_com_cache_expirado_e_503(
    redis_service: RedisService, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    await redis_service.get_trading_hours()

    fake_server.connected = False
    clock.advance(3601)
    with pytest.raises(RedisUnavailableError) as exc:
        await redis_service.get_trading_hours()
    assert exc.value.cache_age is not None
    assert int(exc.value.cache_age) == 3601


async def test_redis_fora_sem_cache_e_503(
    settings: Settings, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    fake_server.connected = False
    client = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)
    service = RedisService(settings, client_factory=lambda: client, now_fn=clock)

    with pytest.raises(RedisUnavailableError, match="nenhum valor em cache local"):
        await service.get_trading_hours()


async def test_cache_com_idade_zero_nao_levanta_typeerror(
    redis_service: RedisService, fake_server: fakeredis.FakeServer
) -> None:
    """Regressão: `if cache_age and ...` caía em `int(None)` na linha seguinte.

    Latente enquanto o cache não tinha evicção, mas a 500 estava a um `clear()` de
    distância.
    """
    await redis_service.get_trading_hours()
    fake_server.connected = False
    # Sem avançar o relógio: idade exatamente 0.0, o valor falsy do guarda antigo.
    assert await redis_service.get_trading_hours() == ("10:00", "18:00")


async def test_reconecta_depois_que_o_redis_volta(
    settings: Settings, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    """Regressão: o cliente era anulado no except e nunca mais reconstruído.

    Com o Redis fora no start do processo, a API respondia 503 para sempre — mesmo
    depois de o Redis voltar. Só um restart resolvia.
    """
    fake_server.connected = False
    criados = 0

    def factory() -> fakeredis.aioredis.FakeRedis:
        nonlocal criados
        criados += 1
        return fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)

    service = RedisService(settings, client_factory=factory, now_fn=clock)
    await service.connect()
    assert not await service.is_connected()

    fake_server.connected = True
    await fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True).set(
        settings.redis_key_open, "10:00"
    )
    await fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True).set(
        settings.redis_key_close, "18:00"
    )

    clock.advance(settings.redis_reconnect_interval_seconds + 1)
    assert await service.get_trading_hours() == ("10:00", "18:00")
    assert criados >= 2


async def test_reconexao_e_throttled(
    settings: Settings, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    """Sem throttle, cada requisição pagaria o socket_connect_timeout inteiro."""
    fake_server.connected = False
    criados = 0

    def factory() -> fakeredis.aioredis.FakeRedis:
        nonlocal criados
        criados += 1
        return fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)

    service = RedisService(settings, client_factory=factory, now_fn=clock)
    await service.connect()
    depois_do_primeiro = criados

    clock.advance(1)  # bem abaixo do intervalo
    with pytest.raises(RedisUnavailableError):
        await service.get_trading_hours()
    assert criados == depois_do_primeiro, "não deve haver nova tentativa antes do intervalo"


async def test_conexoes_concorrentes_conectam_uma_vez(
    settings: Settings, seeded_redis: fakeredis.aioredis.FakeRedis, clock: FakeClock
) -> None:
    criados = 0

    def factory() -> fakeredis.aioredis.FakeRedis:
        nonlocal criados
        criados += 1
        return seeded_redis

    service = RedisService(settings, client_factory=factory, now_fn=clock)
    await asyncio.gather(*(service.get_trading_hours() for _ in range(5)))
    assert criados == 1


async def test_is_connected(redis_service: RedisService, fake_server: fakeredis.FakeServer) -> None:
    await redis_service.connect()
    assert await redis_service.is_connected()

    fake_server.connected = False
    assert not await redis_service.is_connected()


async def test_is_connected_quando_a_fabrica_falha(settings: Settings, clock: FakeClock) -> None:
    """Uma URL inválida faz a fábrica levantar; isso não deve escapar como 500."""

    def factory() -> fakeredis.aioredis.FakeRedis:
        raise OSError("nome não resolve")

    service = RedisService(settings, client_factory=factory, now_fn=clock)
    assert not await service.is_connected()


async def test_is_connected_dispara_reconexao(
    settings: Settings, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    """O health é quem faz poll, então é ele que precisa tentar reconectar.

    Se `is_connected` apenas lesse o cliente em memória, o health reportaria
    "disconnected" para sempre depois de uma queda, mesmo com o Redis de volta.
    """
    fake_server.connected = False

    def factory() -> fakeredis.aioredis.FakeRedis:
        return fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)

    service = RedisService(settings, client_factory=factory, now_fn=clock)
    assert not await service.is_connected()

    fake_server.connected = True
    clock.advance(settings.redis_reconnect_interval_seconds + 1)
    assert await service.is_connected()


async def test_cache_status_com_idade_zero(redis_service: RedisService) -> None:
    """Regressão: idade 0.0 era reportada como None, o que /v1/health lia como
    "não há cache" e classificava como unhealthy."""
    await redis_service.get_trading_hours()
    status = await redis_service.get_cache_status()

    assert status["open_cache_age_seconds"] == 0
    assert status["open_cache_age_seconds"] is not None
    assert status["close_cache_age_seconds"] == 0
    assert status["open_cache_expired"] is False


async def test_cache_status_sem_cache(empty_redis_service: RedisService) -> None:
    status = await empty_redis_service.get_cache_status()
    assert status["open_cache_age_seconds"] is None
    assert status["close_cache_age_seconds"] is None
    assert status["open_cache_expired"] is True


async def test_cache_status_marca_expiracao(redis_service: RedisService, clock: FakeClock) -> None:
    await redis_service.get_trading_hours()

    clock.advance(3600)
    status = await redis_service.get_cache_status()
    assert status["open_cache_expired"] is False

    clock.advance(2)
    status = await redis_service.get_cache_status()
    assert status["open_cache_expired"] is True


async def test_get_open_e_close_isolados(redis_service: RedisService) -> None:
    assert await redis_service.get_open_time() == "10:00"
    assert await redis_service.get_close_time() == "18:00"


async def test_aclose_e_idempotente(redis_service: RedisService) -> None:
    await redis_service.connect()
    await redis_service.aclose()
    await redis_service.aclose()


async def test_connect_nao_propaga_falha(
    settings: Settings, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    fake_server.connected = False
    client = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)
    service = RedisService(settings, client_factory=lambda: client, now_fn=clock)
    await service.connect()  # não deve levantar
    assert not await service.is_connected()


async def test_aclose_tolera_erro_do_cliente(
    settings: Settings, seeded_redis: fakeredis.aioredis.FakeRedis, clock: FakeClock
) -> None:
    """Erro ao fechar não deve propagar e atrapalhar o shutdown."""

    class ClienteQueFalhaAoFechar:
        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            raise OSError("socket já fechado")

    service = RedisService(settings, client_factory=lambda: ClienteQueFalhaAoFechar(), now_fn=clock)  # type: ignore[arg-type,return-value]
    await service.connect()
    await service.aclose()  # não deve levantar


def test_timezone_property(settings: Settings, clock: FakeClock) -> None:
    service = RedisService(settings, now_fn=clock)
    assert str(service.timezone) == "America/Sao_Paulo"


async def test_get_values_com_lista_vazia(redis_service: RedisService) -> None:
    assert await redis_service.get_values([]) == []


async def test_valores_em_bytes_sao_decodificados(settings: Settings, clock: FakeClock) -> None:
    """Um cliente sem decode_responses devolveria bytes; sem normalizar, o valor
    vazaria para a resposta como b'10:00'."""

    class ClienteEmBytes:
        async def ping(self) -> bool:
            return True

        async def mget(self, keys: list[str]) -> list[bytes | None]:
            return [b"10:00", b"18:00"]

        async def aclose(self) -> None:
            return None

    service = RedisService(settings, client_factory=lambda: ClienteEmBytes(), now_fn=clock)  # type: ignore[arg-type,return-value]
    assert await service.get_trading_hours() == ("10:00", "18:00")


async def test_conexao_concorrente_conecta_uma_vez(settings: Settings, clock: FakeClock) -> None:
    """Double-checked locking de `_ensure_client`: duas requisições simultâneas com o
    cliente ainda nulo. A segunda espera o lock e reaproveita o cliente da primeira —
    um único cliente criado, um único ping. No Python 3.14 o ping do fakeredis não
    cede o loop, então só um ping que realmente suspende exercita esse caminho."""

    class SlowPingClient:
        pings = 0

        async def ping(self) -> bool:
            SlowPingClient.pings += 1
            await asyncio.sleep(0)  # cede o loop com o lock em mãos
            return True

        async def aclose(self) -> None:
            return None

    created = 0

    def factory() -> SlowPingClient:
        nonlocal created
        created += 1
        return SlowPingClient()

    service = RedisService(settings, client_factory=factory, now_fn=clock)  # type: ignore[arg-type]
    first, second = await asyncio.gather(service._ensure_client(), service._ensure_client())

    assert first is not None
    assert first is second
    assert created == 1
    assert SlowPingClient.pings == 1
