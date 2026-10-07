"""Contratos internos que o teste de mutação mostrou sem dono.

Cada teste aqui nasceu de um mutante sobrevivente do mutmut: uma mudança no código que a
suíte inteira deixava passar. São mensagens de exceção que vão para o log e para a
resposta, fronteiras de comparação (``<`` contra ``<=``), defaults que nenhum teste
exercitava e as funções extraídas dos handlers.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import fakeredis
import fakeredis.aioredis
import pandas as pd
import pytest
from pydantic import ValidationError

from b3datetime.config import Settings, redact_url
from b3datetime.main import configure_logging
from b3datetime.routers.dates import _dia_de_hoje, _dias_do_periodo, _info_do_calendario
from b3datetime.routers.health import (
    STATUS_HEALTHY,
    STATUS_UNHEALTHY,
    _montar_health,
    _status_do_calendario,
)
from b3datetime.routers.hours import _horario, _horarios
from b3datetime.routers.root import _metadados
from b3datetime.services.calendar_service import (
    CalendarRangeOutOfBoundsError,
    TradingCalendar,
    build_bvmf_calendar,
)
from b3datetime.services.redis_service import (
    InvalidUpstreamValueError,
    KeyNotFoundError,
    RedisService,
    _as_str,
)
from tests.conftest import FakeClock, as_redis
from tests.factories import make_empty_calendar

# --- exceções de domínio ----------------------------------------------------


def test_mensagens_das_excecoes_de_dominio() -> None:
    assert str(KeyNotFoundError("b3:k")) == "Chave 'b3:k' não encontrada no Redis"
    com_chave = InvalidUpstreamValueError("valor ruim", key="b3:k")
    assert (com_chave.key, com_chave.reason) == ("b3:k", "valor ruim")
    assert str(com_chave) == "Valor inválido no Redis (b3:k): valor ruim"
    sem_chave = InvalidUpstreamValueError("valor ruim")
    assert sem_chave.key is None
    assert str(sem_chave) == "Valor inválido no Redis (chave desconhecida): valor ruim"


def test_janela_sem_um_dos_limites_e_tratada_como_calendario_vazio() -> None:
    vazio = "O calendário está vazio e não cobre nenhum período."
    assert str(CalendarRangeOutOfBoundsError(None, date(2024, 1, 1))) == vazio
    assert str(CalendarRangeOutOfBoundsError(date(2024, 1, 1), None)) == vazio


def test_calendario_sem_fim_de_cobertura_nao_cobre_nada() -> None:
    cal = TradingCalendar(pd.DatetimeIndex([]), coverage_start=date(2024, 1, 1))
    assert cal.coverage == (date(2024, 1, 1), None)
    assert not cal.covers(date(2024, 1, 1), date(2024, 1, 1))


def test_razoes_do_valor_invalido() -> None:
    with pytest.raises(InvalidUpstreamValueError) as exc:
        _as_str(b"\xff", "b3:k")
    assert exc.value.reason == "valor não é UTF-8"
    for montar in (lambda: _horarios("25:00", "18:00"), lambda: _horario("abc")):
        with pytest.raises(InvalidUpstreamValueError) as exc:
            montar()
        assert exc.value.reason == "horário fora do formato HH:MM"
        assert isinstance(exc.value.__cause__, ValidationError)


# --- RedisService -----------------------------------------------------------


class _Cliente:
    def __init__(self, valores: list[str | None] | Exception) -> None:
        self.valores = valores

    async def ping(self) -> bool:
        return True

    async def mget(self, _keys: list[str]) -> list[str | None]:
        if isinstance(self.valores, Exception):
            raise self.valores
        return self.valores

    async def aclose(self) -> None:
        return None


async def test_decodificacao_do_redis_py_vira_valor_invalido_com_a_razao(
    settings: Settings, clock: FakeClock
) -> None:
    erro = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    service = RedisService(settings, client_factory=lambda: as_redis(_Cliente(erro)), now_fn=clock)
    with pytest.raises(InvalidUpstreamValueError) as exc:
        await service.get_trading_hours()
    assert exc.value.reason == "valor não é UTF-8"


async def test_mget_com_tamanho_errado_nao_e_truncado_em_silencio(
    settings: Settings, clock: FakeClock
) -> None:
    """``zip(..., strict=True)``: uma resposta com menos valores que chaves é um erro, não
    um horário de fechamento "ausente" que viraria 404."""
    service = RedisService(
        settings, client_factory=lambda: as_redis(_Cliente(["10:00"])), now_fn=clock
    )
    with pytest.raises(ValueError, match="zip"):
        await service.get_trading_hours()


async def test_reconexao_no_limite_exato_do_intervalo(
    settings: Settings, fake_server: fakeredis.FakeServer, clock: FakeClock
) -> None:
    """Fronteira do throttle: decorrido exatamente o intervalo, a nova tentativa acontece."""
    fake_server.connected = False
    tentativas = 0

    def factory() -> fakeredis.aioredis.FakeRedis:
        nonlocal tentativas
        tentativas += 1
        return fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)

    service = RedisService(settings, client_factory=factory, now_fn=clock)
    await service.connect()
    clock.advance(settings.redis_reconnect_interval_seconds)
    await service.is_connected()
    assert tentativas == 2


def test_relogio_padrao_usa_o_fuso_das_settings() -> None:
    settings = Settings(_env_file=None, timezone="Asia/Tokyo")
    agora = RedisService(settings)._now()
    assert agora.tzinfo == ZoneInfo("Asia/Tokyo")
    assert abs(agora - datetime.now(UTC)) < timedelta(seconds=5)


# --- build_bvmf_calendar -----------------------------------------------------


class _CalendarioFalso:
    def __init__(self, sessoes: list[str]) -> None:
        self.sessions = pd.DatetimeIndex(sessoes)


@pytest.fixture
def chamadas(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    registradas: list[dict[str, Any]] = []

    def get_calendar(_nome: str, **kwargs: Any) -> _CalendarioFalso:
        registradas.append(kwargs)
        return _CalendarioFalso(["2024-01-02", "2024-12-30"])

    monkeypatch.setattr(xcals, "get_calendar", get_calendar)
    return registradas


def test_sem_fim_explicito_a_cobertura_termina_na_ultima_sessao(
    chamadas: list[dict[str, Any]],
) -> None:
    cal = build_bvmf_calendar(Settings(_env_file=None), start="2024-01-01")
    assert cal.coverage == (date(2024, 1, 1), date(2024, 12, 30))
    assert chamadas[0]["end"] is None


def test_com_fim_explicito_a_cobertura_vai_ate_ele(chamadas: list[dict[str, Any]]) -> None:
    cal = build_bvmf_calendar(Settings(_env_file=None), start="2024-01-01", end="2024-12-31")
    assert chamadas[0]["end"] == "2024-12-31"
    assert cal.coverage == (date(2024, 1, 1), date(2024, 12, 31))  # feriado: cobre, não é sessão
    assert cal.last_session == date(2024, 12, 30)


def test_inicio_da_janela_movel_usa_o_fuso_das_settings(chamadas: list[dict[str, Any]]) -> None:
    """Etc/GMT-14 e Etc/GMT+12 estão a 26 h de distância: "hoje" é sempre um dia diferente
    nos dois, e o início da janela tem de acompanhar o fuso configurado."""
    build_bvmf_calendar(Settings(_env_file=None, timezone="Etc/GMT-14"))
    build_bvmf_calendar(Settings(_env_file=None, timezone="Etc/GMT+12"))
    leste, oeste = (pd.Timestamp(c["start"]).date() for c in chamadas)
    assert leste - oeste == timedelta(days=1)


# --- configuração e logging --------------------------------------------------


def test_configure_logging_define_nivel_e_formato(monkeypatch: pytest.MonkeyPatch) -> None:
    recebido: dict[str, Any] = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: recebido.update(kw))
    configure_logging()
    assert recebido["level"] == logging.INFO
    assert recebido["format"] == "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def test_redact_url_nao_recodifica_query_sem_credencial() -> None:
    """Só a query com credencial é reescrita: a demais vai byte a byte, mesmo com o que o
    ``urlencode`` escreveria de outro jeito (``%20`` viraria ``+``)."""
    url = "redis://h:6379/0?client_name=a%20b&db=2"
    assert redact_url(url) == url


# --- funções extraídas dos handlers ------------------------------------------


def test_info_do_calendario(test_calendar: TradingCalendar, settings: Settings) -> None:
    info = _info_do_calendario(test_calendar, settings)
    assert info.model_dump() == {
        "exchange": "BVMF",
        "coverage_start": "2024-01-01",
        "coverage_end": "2024-12-31",
        "first_session": "2024-01-02",
        "last_session": "2024-12-31",
        "sessions_count": len(test_calendar),
        "max_range_days": 3660,
    }


def test_dias_do_periodo(test_calendar: TradingCalendar) -> None:
    inicio, fim = date(2024, 2, 9), date(2024, 2, 15)
    assert _dias_do_periodo(test_calendar, inicio, fim, exclude=False, max_range_days=10) == [
        "2024-02-09",
        "2024-02-14",
        "2024-02-15",
    ]
    assert _dias_do_periodo(test_calendar, inicio, fim, exclude=True, max_range_days=10) == [
        "2024-02-10",
        "2024-02-11",
        "2024-02-12",
        "2024-02-13",
    ]


def test_dia_de_hoje_no_fuso_dado(monkeypatch: pytest.MonkeyPatch) -> None:
    from b3datetime.routers import dates

    sp = ZoneInfo("America/Sao_Paulo")
    monkeypatch.setattr(
        dates, "get_current_datetime", lambda tz: datetime(2024, 1, 15, 9, tzinfo=tz)
    )
    cal = TradingCalendar(pd.DatetimeIndex(["2024-01-15"]))
    assert _dia_de_hoje(cal, sp).model_dump() == {"date": "2024-01-15", "is_trading_day": True}


def test_status_do_calendario() -> None:
    assert _status_do_calendario(None).model_dump() == {
        "available": False,
        "first_session": None,
        "last_session": None,
        "sessions_count": None,
    }
    assert _status_do_calendario(make_empty_calendar()).model_dump() == {
        "available": True,
        "first_session": None,
        "last_session": None,
        "sessions_count": 0,
    }


def test_montar_health(test_calendar: TradingCalendar) -> None:
    conectado = {
        "redis_connected": True,
        "open_cache_age_seconds": 0.0,
        "close_cache_age_seconds": 0.0,
        "open_cache_expired": False,
        "close_cache_expired": False,
        "cache_ttl_seconds": 3600,
    }
    tz = ZoneInfo("America/Sao_Paulo")
    saudavel = _montar_health(conectado, test_calendar, tz)
    assert (saudavel.status, saudavel.redis_status) == (STATUS_HEALTHY, "connected")
    assert datetime.fromisoformat(saudavel.timestamp).utcoffset() == timedelta(hours=-3)
    fora = _montar_health(conectado | {"redis_connected": False}, None, tz)
    assert (fora.status, fora.redis_status) == (STATUS_UNHEALTHY, "disconnected")


def test_metadados_com_prefixo() -> None:
    corpo = _metadados(Settings(_env_file=None), "/b3datetime").model_dump()
    assert corpo["docs"] == {
        "swagger": "/b3datetime/docs",
        "redoc": "/b3datetime/redoc",
        "openapi": "/b3datetime/openapi.json",
    }
    assert corpo["endpoints"] == {
        "hours": {
            "all": "/b3datetime/v1/hours",
            "open": "/b3datetime/v1/hours/open",
            "close": "/b3datetime/v1/hours/close",
        },
        "dates": {
            "is_trading_day": "/b3datetime/v1/is-trading-day",
            "trading_days": "/b3datetime/v1/trading-days?start=YYYY-MM-DD&end=YYYY-MM-DD&exclude=false",
            "calendar_info": "/b3datetime/v1/calendar-info",
        },
        "health": "/b3datetime/v1/health",
    }
    assert corpo["authentication"] == {
        "required": False,
        "type": None,
        "header": None,
        "managed_by": "Kong Gateway",
    }


def test_metadados_com_chave_exigida() -> None:
    corpo = _metadados(Settings(_env_file=None, api_key_required=True), "").model_dump()
    assert corpo["authentication"] == {
        "required": True,
        "type": "API Key",
        "header": "apikey",
        "managed_by": "Kong Gateway",
    }
    assert corpo["docs"]["swagger"] == "/docs"


async def test_fetch_reprova_mget_de_tamanho_errado(settings: Settings, clock: FakeClock) -> None:
    """Direto no ``_fetch``: sem ``strict=True`` o ``zip`` truncaria em silêncio."""
    service = RedisService(
        settings, client_factory=lambda: as_redis(_Cliente(["10:00"])), now_fn=clock
    )
    with pytest.raises(ValueError, match="zip"):
        await service._fetch(["a", "b"])


def test_cliente_padrao_usa_os_timeouts_configurados() -> None:
    """Sem ``socket_timeout``, um Redis que aceita a conexão e não responde travaria cada
    requisição pelo tempo que o sistema operacional quisesse."""
    settings = Settings(_env_file=None, redis_socket_timeout_seconds=2.5)
    cliente = RedisService(settings)._default_client_factory()
    kwargs = cliente.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == 2.5
    assert kwargs["socket_connect_timeout"] == 2.5
    assert kwargs["decode_responses"] is True


def test_root_path_perde_so_a_barra_final() -> None:
    """``rstrip("/")``: um prefixo que termina em outra letra fica intacto."""
    from b3datetime.main import create_app

    assert create_app(Settings(_env_file=None, root_path="/LUX/")).root_path == "/LUX"
    assert create_app(Settings(_env_file=None, root_path="/")).root_path == ""


async def test_middleware_sem_root_path_no_scope_nao_mexe_no_caminho() -> None:
    from b3datetime.middleware import RootPathPrefixMiddleware

    visto: dict[str, Any] = {}

    async def app(scope: Any, _receive: Any, _send: Any) -> None:
        visto.update(scope)

    async def receive() -> Any:
        return {"type": "http.request"}

    async def send(_message: Any) -> None:
        return None

    await RootPathPrefixMiddleware(app)({"type": "http", "path": "/v1/hours"}, receive, send)
    assert visto["path"] == "/v1/hours"


def test_redact_url_preserva_parametros_vazios_ao_redigir() -> None:
    """``keep_blank_values=True``: ao reescrever a query, um parâmetro vazio não some."""
    assert redact_url("redis://h/0?password=x&client_name=") == (
        "redis://h/0?password=***&client_name="
    )
