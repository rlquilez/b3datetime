"""Validação do período de ``/v1/trading-days``, chamada direto, sem HTTP.

A ordem das checagens é parte do contrato: um período invertido é rejeitado pela ordem
antes de qualquer conta de span, e o span antes da cobertura — senão a mensagem de erro
apontaria a causa errada.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from b3datetime.routers.dates import _validate_range
from b3datetime.services.calendar_service import TradingCalendar

INICIO = date(2024, 1, 2)


def _mensagem(exc: pytest.ExceptionInfo[HTTPException]) -> str:
    assert exc.value.status_code == 400
    detalhe: object = exc.value.detail
    assert isinstance(detalhe, dict)
    assert detalhe["error"] == "Bad Request"
    return str(detalhe["message"])


def test_periodo_valido_passa(test_calendar: TradingCalendar) -> None:
    _validate_range(test_calendar, INICIO, date(2024, 1, 31), max_range_days=366)


def test_um_dia_so_passa(test_calendar: TradingCalendar) -> None:
    _validate_range(test_calendar, INICIO, INICIO, max_range_days=0)


def test_fim_antes_do_inicio(test_calendar: TradingCalendar) -> None:
    vespera = INICIO - timedelta(days=1)
    with pytest.raises(HTTPException) as exc:
        _validate_range(test_calendar, INICIO, vespera, max_range_days=366)
    assert "maior ou igual" in _mensagem(exc)


def test_span_no_limite_passa_e_um_dia_a_mais_reprova(test_calendar: TradingCalendar) -> None:
    """O span é ``(end - start).days``: com limite 10, 02→12/01 passa e 02→13/01 não."""
    no_limite, um_dia_a_mais = INICIO + timedelta(days=10), INICIO + timedelta(days=11)
    _validate_range(test_calendar, INICIO, no_limite, max_range_days=10)
    with pytest.raises(HTTPException) as exc:
        _validate_range(test_calendar, INICIO, um_dia_a_mais, max_range_days=10)
    mensagem = _mensagem(exc)
    assert "11 dias" in mensagem
    assert "máximo de 10 dias" in mensagem


def test_ordem_e_checada_antes_do_span(test_calendar: TradingCalendar) -> None:
    inicio, fim = date(2030, 1, 1), date(2000, 1, 1)
    with pytest.raises(HTTPException) as exc:
        _validate_range(test_calendar, inicio, fim, max_range_days=1)
    assert "maior ou igual" in _mensagem(exc)


def test_span_e_checado_antes_da_cobertura(test_calendar: TradingCalendar) -> None:
    """Fora da janela E acima do limite: a mensagem é a do limite."""
    inicio, fim = date(2000, 1, 1), date(2030, 1, 1)
    with pytest.raises(HTTPException) as exc:
        _validate_range(test_calendar, inicio, fim, max_range_days=10)
    assert "excede o máximo" in _mensagem(exc)


@pytest.mark.parametrize(
    ("inicio", "fim"),
    [
        (date(2023, 12, 31), date(2024, 1, 5)),  # começa antes da janela
        (date(2024, 12, 20), date(2025, 1, 2)),  # termina depois da janela
    ],
)
def test_fora_da_cobertura(test_calendar: TradingCalendar, inicio: date, fim: date) -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_range(test_calendar, inicio, fim, max_range_days=366)
    assert "2024-01-01" in _mensagem(exc)  # a mensagem informa a janela coberta
