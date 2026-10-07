"""As consultas respondem o que é verdade, e os endpoints concordam entre si.

Contra o calendário BVMF real e o Redis real — nada de dados sintéticos. As datas são
derivadas de hoje e da janela servida, nunca fixas, porque a janela anda todo dia: um
teste que fixasse "2026" apodreceria quando 2026 saísse da cobertura.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import pytest

from tests.e2e.calendario_b3 import SESSOES_POR_ANO, anos_atras, fechamentos_da_b3, quarta_de_cinzas
from tests.e2e.conftest import CHAVE_ABERTURA, CHAVE_FECHAMENTO, Ambiente, hoje
from tests.e2e.contrato import Contrato

pytestmark = pytest.mark.e2e


def _datas(amb: Ambiente, inicio: date, fim: date, *, exclude: bool = False) -> list[date]:
    r = amb.http.get(
        "/v1/trading-days",
        params={
            "start": inicio.isoformat(),
            "end": fim.isoformat(),
            "exclude": str(exclude).lower(),
        },
    )
    assert r.status_code == 200, r.text
    return [date.fromisoformat(d) for d in r.json()]


def _info(amb: Ambiente) -> dict[str, Any]:
    r = amb.http.get("/v1/calendar-info")
    assert r.status_code == 200, r.text
    info = r.json()
    assert isinstance(info, dict)
    return info


def _ano_passado() -> tuple[date, date]:
    ano = hoje().year - 1
    return date(ano, 1, 1), date(ano, 12, 31)


def test_ano_completo_respeita_os_feriados_da_b3(principal: Ambiente) -> None:
    inicio, fim = _ano_passado()
    dias = _datas(principal, inicio, fim)

    assert dias == sorted(set(dias)), "datas fora de ordem ou repetidas"
    assert all(inicio <= d <= fim for d in dias)
    assert not [d for d in dias if d.weekday() >= 5], "pregão em fim de semana"
    abertos = {nome: d for nome, d in fechamentos_da_b3(inicio.year).items() if d in dias}
    assert not abertos, f"pregão em dia em que a B3 não abre: {abertos}"
    assert quarta_de_cinzas(inicio.year) in dias, "Quarta de Cinzas tem pregão"
    assert len(dias) in SESSOES_POR_ANO


def test_exclude_e_o_complemento_exato(principal: Ambiente) -> None:
    inicio, fim = _ano_passado()
    com = set(_datas(principal, inicio, fim))
    sem = set(_datas(principal, inicio, fim, exclude=True))

    todos = {inicio + timedelta(days=n) for n in range((fim - inicio).days + 1)}
    assert not com & sem
    assert com | sem == todos
    assert {d for d in todos if d.weekday() >= 5} <= sem


def test_contagem_do_calendar_info_bate_com_trading_days(principal: Ambiente) -> None:
    """``sessions_count`` é o total de pregões da cobertura, lida em blocos de até
    ``max_range_days`` — o span máximo que ``/v1/trading-days`` aceita."""
    info = _info(principal)
    inicio = date.fromisoformat(info["coverage_start"])
    fim = date.fromisoformat(info["coverage_end"])
    passo = timedelta(days=info["max_range_days"])

    dias: list[date] = []
    while inicio <= fim:
        bloco_fim = min(inicio + passo, fim)
        dias += _datas(principal, inicio, bloco_fim)
        inicio = bloco_fim + timedelta(days=1)

    assert len(dias) == info["sessions_count"]
    assert dias == sorted(set(dias))
    assert (dias[0].isoformat(), dias[-1].isoformat()) == (
        info["first_session"],
        info["last_session"],
    )


def test_janela_do_calendario_e_movel_e_coerente(principal: Ambiente) -> None:
    info = _info(principal)
    inicio = date.fromisoformat(info["coverage_start"])
    primeira = date.fromisoformat(info["first_session"])
    ultima = date.fromisoformat(info["last_session"])
    referencia = hoje()

    # ±1 dia: o calendário é construído quando o container sobe, que pode ter sido antes
    # da meia-noite.
    assert abs((inicio - anos_atras(referencia, 10)).days) <= 1, "a janela começa há 10 anos"
    assert inicio <= primeira <= inicio + timedelta(days=7)
    assert primeira.weekday() < 5
    assert info["coverage_end"] == info["last_session"]
    assert ultima > referencia, "o calendário deveria cobrir datas futuras"


def test_health_concorda_com_calendar_info(principal: Ambiente) -> None:
    """Regressão de #46: o health anunciava o início da janela como primeira sessão."""
    health = principal.http.get("/v1/health").json()["calendar"]
    info = _info(principal)
    assert (health["first_session"], health["last_session"], health["sessions_count"]) == (
        info["first_session"],
        info["last_session"],
        info["sessions_count"],
    )


def test_is_trading_day_concorda_com_trading_days(principal: Ambiente) -> None:
    antes = hoje()
    r = principal.http.get("/v1/is-trading-day")
    depois = hoje()
    assert r.status_code == 200, r.text
    dia = date.fromisoformat(r.json()["date"])

    assert dia in {antes, depois}, "a data deveria ser hoje em America/Sao_Paulo"
    assert r.json()["is_trading_day"] is (dia in _datas(principal, dia, dia))
    if dia.weekday() >= 5:
        assert r.json()["is_trading_day"] is False


def test_horarios_refletem_o_redis_ao_vivo(principal: Ambiente) -> None:
    """A leitura é do Redis a cada requisição; o cache local só serve com ele fora."""
    if principal.redis is None or principal.horarios is None:
        pytest.skip("exige controlar o Redis do ambiente (E2E_IMAGE)")
    try:
        principal.redis.set(CHAVE_ABERTURA, "09:30")
        principal.redis.set(CHAVE_FECHAMENTO, "18:15")
        assert principal.http.get("/v1/hours").json() == {"open": "09:30", "close": "18:15"}
        assert principal.http.get("/v1/hours/open").json() == {"time": "09:30"}
        assert principal.http.get("/v1/hours/close").json() == {"time": "18:15"}
    finally:
        principal.redis.set(CHAVE_ABERTURA, principal.horarios["open"])
        principal.redis.set(CHAVE_FECHAMENTO, principal.horarios["close"])
    assert principal.http.get("/v1/hours").json() == principal.horarios


def test_raiz_anuncia_exatamente_o_que_esta_publicado(
    principal: Ambiente, contrato: Contrato
) -> None:
    raiz = principal.http.get("/").json()
    p = principal.prefixo
    links = raiz["endpoints"]
    anunciados = {
        *links["hours"].values(),
        *(link.split("?")[0] for link in links["dates"].values()),
        links["health"],
    }

    assert anunciados == {p + caminho for caminho in contrato.documento["paths"]} - {p + "/"}
    assert raiz["docs"] == {
        "swagger": f"{p}/docs",
        "redoc": f"{p}/redoc",
        "openapi": f"{p}/openapi.json",
    }
    assert raiz["version"] == contrato.documento["info"]["version"]
    # O build em execução: o CI passa o commit esperado (E2E_BUILD); sem ele, basta existir.
    esperado = os.environ.get("E2E_BUILD")
    assert raiz["build"] == esperado if esperado else raiz["build"]
    # Sem autenticação: nem GET / nem o schema podem prometer um header.
    assert raiz["authentication"]["required"] is ("security" in contrato.documento)


def test_openapi_declara_o_prefixo_em_servers(principal: Ambiente, contrato: Contrato) -> None:
    if principal.prefixo:
        assert contrato.documento["servers"] == [{"url": principal.prefixo}]
