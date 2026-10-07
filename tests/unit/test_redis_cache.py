"""Cache local, com relógio injetado."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from b3datetime.services.redis_service import RedisCache
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


def test_gravar_de_novo_substitui_o_valor_e_zera_a_idade(clock: FakeClock) -> None:
    cache = make_cache(clock)
    cache.set("k", "v1")
    clock.advance(30)
    cache.set("k", "v2")
    assert cache.get_value("k") == "v2"
    assert cache.get_age_seconds("k") == 0.0


# Fim do horário de verão em Nova York, 03/11/2024: às 02:00 EDT o relógio volta para 01:00
# EST. 00:30 EDT (04:30 UTC) e 01:30 EST (06:30 UTC) estão a 2 h reais de distância, mas a
# 1 h de "relógio de parede". O fuso é configurável (TIMEZONE); São Paulo não tem horário de
# verão desde 2019, mas a idade do cache não pode depender disso.
NY = ZoneInfo("America/New_York")
ANTES_DA_VIRADA = datetime(2024, 11, 3, 0, 30, tzinfo=NY)
DEPOIS_DA_VIRADA = datetime(2024, 11, 3, 1, 30, fold=1, tzinfo=NY)


def test_idade_atravessa_o_fim_do_horario_de_verao() -> None:
    """Regressão: subtrair datetimes com a MESMA ZoneInfo dá a diferença de relógio de
    parede. A idade saía 3600 s em vez de 7200 s, e um cache vencido (TTL de 1 h) seguia
    sendo servido como válido."""
    instantes = iter([ANTES_DA_VIRADA, DEPOIS_DA_VIRADA, DEPOIS_DA_VIRADA])
    cache = RedisCache(now_fn=lambda: next(instantes))
    cache.set("k", "v")
    assert cache.get_age_seconds("k") == 7200
    assert cache.is_expired("k", TTL)
