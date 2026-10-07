"""``TradingCalendar`` e a validação de período, sobre calendários e intervalos gerados.

* sessões ⊔ não-sessões = todos os dias do intervalo, sem sobreposição, cada lista ordenada
  e sem repetição — é o que ``exclude=true`` promete ser o complemento exato;
* ``is_session`` concorda com ``sessions_in_range`` dia a dia;
* intervalo invertido devolve listas vazias;
* ``_validate_range`` reprova se e somente se o período está invertido, excede o limite ou
  sai da cobertura — e nessa ordem de precedência.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from hypothesis import given
from hypothesis import strategies as st

from b3datetime.routers.dates import _validate_range
from b3datetime.services.calendar_service import TradingCalendar
from tests.e2e.calendario_b3 import pascoa
from tests.property.estrategias import DATAS, calendarios

DESLOCAMENTO = st.integers(min_value=-30, max_value=150)


@st.composite
def calendario_e_intervalo(draw: st.DrawFn) -> tuple[TradingCalendar, date, date]:
    cal = draw(calendarios())
    base = cal.coverage[0] or date(2024, 1, 1)
    inicio = base + timedelta(days=draw(DESLOCAMENTO))
    fim = inicio + timedelta(days=draw(st.integers(min_value=-5, max_value=150)))
    return cal, inicio, fim


@given(calendario_e_intervalo())
def test_sessoes_e_nao_sessoes_particionam_o_intervalo(
    caso: tuple[TradingCalendar, date, date],
) -> None:
    cal, inicio, fim = caso
    sessoes = cal.sessions_in_range(inicio, fim)
    fechados = cal.non_sessions_in_range(inicio, fim)
    if fim < inicio:
        assert sessoes == []
        assert fechados == []
        return
    dias = {inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)}
    assert set(sessoes).isdisjoint(fechados)
    assert set(sessoes) | set(fechados) == dias
    assert len(sessoes) + len(fechados) == len(dias)
    assert sessoes == sorted(set(sessoes))
    assert fechados == sorted(set(fechados))


@given(calendario_e_intervalo())
def test_is_session_concorda_com_sessions_in_range(
    caso: tuple[TradingCalendar, date, date],
) -> None:
    cal, inicio, fim = caso
    if fim < inicio:
        return
    sessoes = set(cal.sessions_in_range(inicio, fim))
    for i in range((fim - inicio).days + 1):
        dia = inicio + timedelta(days=i)
        assert cal.is_session(dia) == (dia in sessoes)


@given(calendario_e_intervalo(), st.integers(min_value=0, max_value=200))
def test_validate_range_segue_o_oraculo(
    caso: tuple[TradingCalendar, date, date], limite: int
) -> None:
    cal, inicio, fim = caso
    cobertura_inicio, cobertura_fim = cal.coverage
    if fim < inicio:
        esperado: str | None = "maior ou igual"
    elif (fim - inicio).days > limite:
        esperado = "excede o máximo"
    elif not (
        cobertura_inicio is not None
        and cobertura_fim is not None
        and cobertura_inicio <= inicio
        and fim <= cobertura_fim
    ):
        esperado = "fora da janela"
    else:
        esperado = None

    if esperado is None:
        _validate_range(cal, inicio, fim, limite)  # não pode levantar
        return
    with pytest.raises(HTTPException) as exc:
        _validate_range(cal, inicio, fim, limite)
    assert exc.value.status_code == 400
    detalhe: object = exc.value.detail
    assert isinstance(detalhe, dict)
    assert esperado in str(detalhe["message"])


@given(st.integers(min_value=1583, max_value=4099))
def test_pascoa_e_um_domingo_entre_22_de_marco_e_25_de_abril(ano: int) -> None:
    """O oráculo dos feriados móveis da B3 (``calendario_b3.pascoa``) contra a definição.

    Comparado com ``dateutil.easter`` (o algoritmo de referência) e com os limites
    canônicos do calendário gregoriano.
    """
    from dateutil.easter import easter

    domingo = pascoa(ano)
    assert domingo == easter(ano)
    assert domingo.weekday() == 6
    assert date(ano, 3, 22) <= domingo <= date(ano, 4, 25)


@given(DATAS)
def test_datas_geradas_estao_na_faixa(dia: date) -> None:
    """Sanidade da estratégia compartilhada (evita uma estratégia vazia passar em branco)."""
    assert date(2000, 1, 1) <= dia <= date(2040, 12, 31)
