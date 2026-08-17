"""Cache local, com relógio injetado."""

from __future__ import annotations

from src.services.redis_service import RedisCache
from tests.conftest import FakeClock

TTL = 3600


def make_cache(clock: FakeClock) -> RedisCache:
    return RedisCache(now_fn=clock)


def test_set_get(clock: FakeClock) -> None:
    cache = make_cache(clock)
    cache.set("k", "v")
    assert cache.get_value("k") == "v"


def test_get_de_chave_ausente(clock: FakeClock) -> None:
    assert make_cache(clock).get_value("nao-existe") is None


def test_idade_de_chave_ausente_e_none(clock: FakeClock) -> None:
    assert make_cache(clock).get_age_seconds("nao-existe") is None


def test_idade_zero_e_zero_e_nao_none(clock: FakeClock) -> None:
    """Regressão: `int(age) if age else None` transformava idade 0.0 em None.

    Como None é a sentinela de "não há cache", um cache recém-escrito era reportado
    como ausente — os dois estados ficavam semanticamente invertidos.
    """
    cache = make_cache(clock)
    cache.set("k", "v")
    age = cache.get_age_seconds("k")
    assert age == 0.0
    assert age is not None
    assert not cache.is_expired("k", TTL)


def test_fronteira_do_ttl(clock: FakeClock) -> None:
    cache = make_cache(clock)
    cache.set("k", "v")

    clock.advance(TTL)
    assert not cache.is_expired("k", TTL), "idade == ttl ainda é válido"

    clock.advance(1)
    assert cache.is_expired("k", TTL)


def test_chave_ausente_conta_como_expirada(clock: FakeClock) -> None:
    assert make_cache(clock).is_expired("nao-existe", TTL)


def test_set_atualiza_o_timestamp(clock: FakeClock) -> None:
    cache = make_cache(clock)
    cache.set("k", "v")
    clock.advance(100)
    assert cache.get_age_seconds("k") == 100

    cache.set("k", "v2")
    assert cache.get_age_seconds("k") == 0.0


def test_string_vazia_e_um_valor_legitimo(clock: FakeClock) -> None:
    """Regressão: `if value:` tratava string vazia como ausência de valor."""
    cache = make_cache(clock)
    cache.set("k", "")
    assert cache.get_value("k") == ""
    assert cache.get_value("k") is not None
    assert cache.get_age_seconds("k") == 0.0


def test_clear(clock: FakeClock) -> None:
    cache = make_cache(clock)
    cache.set("k", "v")
    cache.clear()
    assert cache.get_value("k") is None
    assert cache.get_age_seconds("k") is None


def test_get_devolve_valor_e_timestamp(clock: FakeClock) -> None:
    cache = make_cache(clock)
    cache.set("k", "v")
    entry = cache.get("k")
    assert entry is not None
    assert entry[0] == "v"
    assert entry[1] == clock.now()
