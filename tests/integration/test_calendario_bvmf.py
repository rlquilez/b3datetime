"""O calendário BVMF real, construído pelo ``exchange_calendars``.

Sempre com ``start``/``end`` explícitos: a janela de produção anda todo dia, e um teste
que dependesse dela apodreceria. Estes testes protegem contra o que nenhum teste com
calendário sintético enxerga — uma atualização do ``exchange_calendars`` (ou do
``pandas``) que mude feriados, a construção da janela ou a leitura de ``.sessions``.
"""

from __future__ import annotations

from datetime import date

import pytest

from b3datetime.config import Settings
from b3datetime.main import create_app
from b3datetime.routers.dates import _dias_do_periodo
from b3datetime.services.calendar_service import TradingCalendar, build_bvmf_calendar
from tests.e2e.calendario_b3 import SESSOES_POR_ANO, fechamentos_da_b3, quarta_de_cinzas

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Anos cujas regras foram conferidas contra o calendário real (ver tests/e2e/calendario_b3.py).
ANOS = range(2017, 2026)


@pytest.fixture(scope="module")
def calendario_2017_2025() -> TradingCalendar:
    return build_bvmf_calendar(Settings(_env_file=None), start="2017-01-01", end="2025-12-31")


def test_calendario_real_da_bvmf() -> None:
    calendario = build_bvmf_calendar(Settings(_env_file=None), start="2024-01-01", end="2024-12-31")
    assert not calendario.is_session(date(2024, 1, 1))  # Confraternização
    assert not calendario.is_session(date(2024, 2, 12))  # Carnaval
    assert calendario.is_session(date(2024, 1, 2))
    # A cobertura é a janela pedida — começa e termina em dias sem pregão (Confraternização
    # e o último dia do ano) —, e não o intervalo entre a primeira e a última sessão.
    assert calendario.coverage == (date(2024, 1, 1), date(2024, 12, 31))
    assert calendario.first_session == date(2024, 1, 2)
    assert calendario.last_session == date(2024, 12, 30)


@pytest.mark.parametrize("ano", ANOS)
def test_b3_nunca_abre_nos_fechamentos_conhecidos(
    calendario_2017_2025: TradingCalendar, ano: int
) -> None:
    abertos = {
        nome: dia
        for nome, dia in fechamentos_da_b3(ano).items()
        if calendario_2017_2025.is_session(dia)
    }
    assert not abertos, f"o calendário real abre em fechamentos da B3: {abertos}"


@pytest.mark.parametrize("ano", ANOS)
def test_ano_tem_sessoes_plausiveis_e_nenhuma_em_fim_de_semana(
    calendario_2017_2025: TradingCalendar, ano: int
) -> None:
    sessoes = calendario_2017_2025.sessions_in_range(date(ano, 1, 1), date(ano, 12, 31))
    assert len(sessoes) in SESSOES_POR_ANO
    assert all(dia.weekday() < 5 for dia in sessoes)
    # Quarta-feira de Cinzas tem pregão (à tarde), apesar de vir depois do Carnaval.
    assert quarta_de_cinzas(ano) in sessoes


def test_complemento_cobre_exatamente_o_intervalo(calendario_2017_2025: TradingCalendar) -> None:
    inicio, fim = date(2025, 1, 1), date(2025, 12, 31)
    sessoes = calendario_2017_2025.sessions_in_range(inicio, fim)
    fechados = calendario_2017_2025.non_sessions_in_range(inicio, fim)
    assert not set(sessoes) & set(fechados)
    assert len(sessoes) + len(fechados) == (fim - inicio).days + 1
    assert min(sessoes + fechados) == inicio
    assert max(sessoes + fechados) == fim


def test_exemplos_de_trading_days_sao_a_resposta_real_do_periodo_de_exemplo() -> None:
    """O período de exemplo dos parâmetros e os dois exemplos de 200 são um par: quem usa
    o "Try it out" — e o ZAP, que importa os mesmos exemplos — recebe exatamente o que a
    documentação mostra, com e sem ``exclude``."""
    settings = Settings(_env_file=None)
    operacao = create_app(settings).openapi()["paths"]["/v1/trading-days"]["get"]
    periodo = {
        p["name"]: date.fromisoformat(p["examples"]["exemplo"]["value"])
        for p in operacao["parameters"]
        if p["name"] in {"start", "end"}
    }
    exemplos = operacao["responses"]["200"]["content"]["application/json"]["examples"]
    calendario = build_bvmf_calendar(settings, start="2026-01-01", end="2026-12-31")

    for exclude, nome in ((False, "trading_days"), (True, "non_trading_days")):
        dias = _dias_do_periodo(
            calendario,
            periodo["start"],
            periodo["end"],
            exclude=exclude,
            max_range_days=settings.max_range_days,
        )
        assert dias == exemplos[nome]["value"], nome
