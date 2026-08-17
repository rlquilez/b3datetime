"""Calendário de negociação: cobertura, recorte e complemento."""

from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd
import pytest

from src.config import Settings
from src.services.calendar_service import (
    CalendarRangeOutOfBoundsError,
    CalendarUnavailableError,
    TradingCalendar,
    build_bvmf_calendar,
)
from tests.factories import make_calendar, make_empty_calendar


def test_is_session_em_dia_util(test_calendar: TradingCalendar) -> None:
    assert test_calendar.is_session(date(2024, 1, 15))  # segunda-feira comum


def test_is_session_em_sabado(test_calendar: TradingCalendar) -> None:
    assert not test_calendar.is_session(date(2024, 1, 13))


def test_is_session_em_feriado(test_calendar: TradingCalendar) -> None:
    assert not test_calendar.is_session(date(2024, 2, 12))  # Carnaval


def test_sessions_in_range_inclusivo(test_calendar: TradingCalendar) -> None:
    dias = test_calendar.sessions_in_range(date(2024, 1, 2), date(2024, 1, 5))
    assert dias == [date(2024, 1, d) for d in (2, 3, 4, 5)]


def test_sessions_in_range_em_fim_de_semana(test_calendar: TradingCalendar) -> None:
    assert test_calendar.sessions_in_range(date(2024, 1, 13), date(2024, 1, 14)) == []


def test_non_sessions_e_o_complemento_exato(test_calendar: TradingCalendar) -> None:
    start, end = date(2024, 1, 1), date(2024, 1, 31)
    sessoes = set(test_calendar.sessions_in_range(start, end))
    nao_sessoes = set(test_calendar.non_sessions_in_range(start, end))

    todos = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    assert sessoes | nao_sessoes == todos
    assert sessoes & nao_sessoes == set()


def test_non_sessions_pega_feriado_e_fim_de_semana(test_calendar: TradingCalendar) -> None:
    dias = test_calendar.non_sessions_in_range(date(2024, 1, 1), date(2024, 1, 8))
    assert date(2024, 1, 1) in dias  # feriado
    assert date(2024, 1, 6) in dias  # sábado
    assert date(2024, 1, 7) in dias  # domingo
    assert date(2024, 1, 2) not in dias  # sessão


def test_cobertura_e_sessoes_sao_distintas(test_calendar: TradingCalendar) -> None:
    """A cobertura inclui 1º de janeiro (feriado); a primeira sessão é o dia 2.

    Confundir os dois faria a API rejeitar com 400 um período que sabe responder,
    só porque começa num feriado.
    """
    assert test_calendar.coverage == (date(2024, 1, 1), date(2024, 12, 31))
    assert test_calendar.first_session == date(2024, 1, 2)
    assert test_calendar.last_session == date(2024, 12, 31)


def test_covers(test_calendar: TradingCalendar) -> None:
    assert test_calendar.covers(date(2024, 3, 1), date(2024, 3, 31))
    assert not test_calendar.covers(date(2010, 1, 1), date(2010, 12, 31))


def test_periodo_totalmente_fora_da_janela_levanta(test_calendar: TradingCalendar) -> None:
    """Regressão: o período fora da janela devolvia [] com HTTP 200.

    A API afirmava que a B3 não teve nenhum dia de negociação no ano inteiro.
    """
    with pytest.raises(CalendarRangeOutOfBoundsError) as exc:
        test_calendar.require_coverage(date(2010, 1, 1), date(2010, 12, 31))

    assert exc.value.coverage_start == date(2024, 1, 1)
    assert exc.value.coverage_end == date(2024, 12, 31)
    assert "2024-01-01" in str(exc.value)


def test_periodo_fora_da_janela_nao_vira_lista_de_nao_negociacao(
    test_calendar: TradingCalendar,
) -> None:
    """Regressão: com exclude=true, um período fora da janela devolvia todos os dias
    como "sem negociação" — o pior dos dois caminhos, porque parecia plausível."""
    with pytest.raises(CalendarRangeOutOfBoundsError):
        test_calendar.require_coverage(date(2010, 1, 1), date(2010, 12, 31))


def test_periodo_parcialmente_coberto_tambem_e_rejeitado(
    test_calendar: TradingCalendar,
) -> None:
    with pytest.raises(CalendarRangeOutOfBoundsError):
        test_calendar.require_coverage(date(2023, 12, 1), date(2024, 3, 1))

    with pytest.raises(CalendarRangeOutOfBoundsError):
        test_calendar.require_coverage(date(2024, 12, 1), date(2025, 3, 1))


def test_cobertura_sem_janela_explicita_usa_as_sessoes() -> None:
    cal = TradingCalendar(pd.DatetimeIndex([pd.Timestamp("2024-03-04")]))
    assert cal.coverage == (date(2024, 3, 4), date(2024, 3, 4))


def test_calendario_vazio_nao_estoura() -> None:
    vazio = make_empty_calendar()
    assert vazio.bounds == (None, None)
    assert not vazio.covers(date(2024, 1, 1), date(2024, 1, 2))
    assert len(vazio) == 0

    with pytest.raises(CalendarRangeOutOfBoundsError, match="vazio"):
        vazio.require_coverage(date(2024, 1, 1), date(2024, 1, 2))


def test_len(test_calendar: TradingCalendar) -> None:
    assert len(test_calendar) > 240  # ~252 pregões num ano


def test_custo_do_complemento_nao_escala_com_o_numero_de_sessoes() -> None:
    """Regressão de performance: a checagem era O(dias x sessoes) sobre uma lista.

    Um cronômetro simples não serve aqui: com `max_range_days` limitando o span a
    3660 dias, mesmo a versão quadrática termina em ~0,1 s, então qualquer limiar de
    tempo absoluto passaria com o bug presente. O que se mede é o **escalonamento**:
    fixando o intervalo de dias e multiplicando o número de sessões por ~40, uma
    busca com hash mantém o tempo praticamente constante, enquanto a varredura
    linear cresce proporcionalmente.
    """
    inicio, fim = date(2024, 1, 1), date(2024, 12, 31)
    poucas = TradingCalendar(pd.DatetimeIndex(pd.bdate_range("2024-01-01", "2024-12-31")))
    muitas = TradingCalendar(pd.DatetimeIndex(pd.date_range("1940-01-01", "2050-12-31")))
    assert len(muitas) > 30 * len(poucas)

    def cronometrar(cal: TradingCalendar) -> float:
        t0 = time.perf_counter()
        for _ in range(3):
            cal.non_sessions_in_range(inicio, fim)
        return time.perf_counter() - t0

    cronometrar(poucas)  # aquece o interpretador
    tempo_poucas = cronometrar(poucas)
    tempo_muitas = cronometrar(muitas)

    fator = tempo_muitas / max(tempo_poucas, 1e-6)
    assert fator < 5, (
        f"o tempo cresceu {fator:.1f}x com {len(muitas) // len(poucas)}x mais sessões; "
        "a busca voltou a ser linear"
    )


def test_pertinencia_usa_container_com_hash() -> None:
    """Invariante estrutural que sustenta o teste de escalonamento acima."""
    cal = make_calendar()
    assert isinstance(cal._session_dates, frozenset)


def test_build_bvmf_calendar_traduz_falha(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falha de construção vira CalendarUnavailableError, não RuntimeError cru."""
    import src.services.calendar_service as mod

    def boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("catálogo corrompido")

    monkeypatch.setattr(mod.xcals, "get_calendar", boom)
    with pytest.raises(CalendarUnavailableError, match="BVMF"):
        build_bvmf_calendar(Settings(_env_file=None))


def test_build_bvmf_calendar_preserva_a_causa(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.services.calendar_service as mod

    original = ValueError("causa original")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise original

    monkeypatch.setattr(mod.xcals, "get_calendar", boom)
    with pytest.raises(CalendarUnavailableError) as exc:
        build_bvmf_calendar(Settings(_env_file=None))
    assert exc.value.__cause__ is original


@pytest.mark.slow
def test_calendario_real_da_bvmf() -> None:
    """Sempre com start/end explícitos: a janela de produção se move todo dia."""
    calendario = build_bvmf_calendar(Settings(_env_file=None), start="2024-01-01", end="2024-12-31")
    assert not calendario.is_session(date(2024, 1, 1))  # Confraternização
    assert not calendario.is_session(date(2024, 2, 12))  # Carnaval
    assert calendario.is_session(date(2024, 1, 2))
    first, _ = calendario.bounds
    assert first is not None
    assert first >= date(2024, 1, 1)
