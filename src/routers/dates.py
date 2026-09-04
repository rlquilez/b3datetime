"""Endpoints de dias de negociação da B3.

A validação de período é feita contra os **limites reais** do calendário carregado,
lidos a cada requisição. A versão anterior validava contra a constante 2006 enquanto o
calendário cobria apenas os últimos dez anos, e como o recorte era feito por máscara
sobre o índice de sessões, um período fora da cobertura devolvia HTTP 200 com uma
lista vazia — ou, com ``exclude=true``, com todos os dias do período marcados como
"sem negociação". Os limites também eram congelados no import, então a resposta
dependia de quando o processo havia subido.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.config import get_current_datetime
from src.dependencies import CalendarDep, SettingsDep
from src.routers.openapi_examples import (
    CALENDAR_INFO_EXAMPLE,
    RESPONSE_CALENDAR_UNAVAILABLE,
    RESPONSE_RANGE_INVALID,
    TAG_DATES,
    examples_response,
    success_response,
)
from src.services.calendar_service import CalendarRangeOutOfBoundsError, TradingCalendar

router = APIRouter(prefix="/v1", tags=[TAG_DATES])


class TradingDayResponse(BaseModel):
    """Resultado da verificação de um dia de negociação."""

    date: str = Field(
        ...,
        description="Data verificada no formato YYYY-MM-DD",
        json_schema_extra={"example": "2026-09-04"},
    )
    is_trading_day: bool = Field(
        ...,
        description="Se é um dia de negociação na B3",
        json_schema_extra={"example": True},
    )


class CalendarInfoResponse(BaseModel):
    """Limites vigentes do calendário carregado."""

    exchange: str = Field(
        ...,
        description="Código da bolsa no exchange_calendars",
        json_schema_extra={"example": "BVMF"},
    )
    coverage_start: str = Field(
        ...,
        description="Primeira data respondível. Períodos que comecem antes são rejeitados",
        json_schema_extra={"example": "2016-09-04"},
    )
    coverage_end: str = Field(
        ...,
        description="Última data respondível",
        json_schema_extra={"example": "2027-09-03"},
    )
    first_session: str = Field(
        ...,
        description="Primeiro dia de negociação dentro da cobertura",
        json_schema_extra={"example": "2016-09-05"},
    )
    last_session: str = Field(
        ...,
        description="Último dia de negociação dentro da cobertura",
        json_schema_extra={"example": "2027-09-03"},
    )
    sessions_count: int = Field(
        ...,
        description="Quantidade de dias de negociação na cobertura",
        json_schema_extra={"example": 2730},
    )
    max_range_days: int = Field(
        ...,
        description="Span máximo aceito por /v1/trading-days, em dias",
        json_schema_extra={"example": 3660},
    )


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "Bad Request", "message": message},
    )


def _validate_range(calendar: TradingCalendar, start: date, end: date, max_range_days: int) -> None:
    """Valida ordem, span e cobertura do período pedido."""
    if end < start:
        raise _bad_request("A data final deve ser maior ou igual à data inicial")

    span_days = (end - start).days
    if span_days > max_range_days:
        raise _bad_request(
            f"O período pedido tem {span_days} dias e excede o máximo de "
            f"{max_range_days} dias por requisição"
        )

    try:
        calendar.require_coverage(start, end)
    except CalendarRangeOutOfBoundsError as exc:
        raise _bad_request(str(exc)) from exc


@router.get(
    "/calendar-info",
    summary="Consultar os limites do calendário",
    description="""Retorna os limites vigentes do calendário carregado.

A janela do calendário é **móvel** e se desloca conforme o tempo passa, portanto
consulte este endpoint em vez de assumir uma data mínima fixa. Períodos fora destes
limites são rejeitados com 400 por `/v1/trading-days`.

`coverage_*` é o intervalo respondível; `first_session`/`last_session` são o primeiro e
o último pregão dentro dele. Os dois diferem quando a janela começa num feriado ou fim
de semana.""",
    responses={
        200: success_response("Limites obtidos com sucesso", CALENDAR_INFO_EXAMPLE),
        503: RESPONSE_CALENDAR_UNAVAILABLE,
    },
)
async def get_calendar_info(calendar: CalendarDep, settings: SettingsDep) -> CalendarInfoResponse:
    """Limites vigentes do calendário."""
    coverage_start, coverage_end = calendar.coverage
    first, last = calendar.first_session, calendar.last_session
    if coverage_start is None or coverage_end is None or first is None or last is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "Service Unavailable", "message": "Calendário vazio"},
        )
    return CalendarInfoResponse(
        exchange=settings.exchange_name,
        coverage_start=coverage_start.isoformat(),
        coverage_end=coverage_end.isoformat(),
        first_session=first.isoformat(),
        last_session=last.isoformat(),
        sessions_count=len(calendar),
        max_range_days=settings.max_range_days,
    )


@router.get(
    "/is-trading-day",
    summary="Verificar se hoje é dia de negociação",
    description="""Verifica se o dia atual é um dia de negociação na B3, considerando feriados e
finais de semana do calendário BVMF.

O "dia atual" é determinado no timezone America/Sao_Paulo. Se ele estiver fora da
janela do calendário a resposta é 503 — nunca `false`, que seria indistinguível de um
feriado legítimo.""",
    responses={
        200: examples_response(
            "Verificação realizada com sucesso",
            {
                "trading_day": {
                    "summary": "Dia de negociação",
                    "value": {"date": "2026-09-04", "is_trading_day": True},
                },
                "non_trading_day": {
                    "summary": "Não é dia de negociação",
                    "value": {"date": "2026-09-05", "is_trading_day": False},
                },
            },
        ),
        503: RESPONSE_CALENDAR_UNAVAILABLE,
    },
)
async def is_trading_day(calendar: CalendarDep, settings: SettingsDep) -> TradingDayResponse:
    """Verifica se hoje é dia de negociação na B3."""
    today = get_current_datetime(settings.tz).date()
    # Sem esta checagem, um "hoje" fora da janela responderia `false` — indistinguível
    # de um feriado legítimo.
    try:
        calendar.require_coverage(today, today)
    except CalendarRangeOutOfBoundsError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "Service Unavailable", "message": str(exc)},
        ) from exc

    return TradingDayResponse(date=today.isoformat(), is_trading_day=calendar.is_session(today))


@router.get(
    "/trading-days",
    summary="Listar dias de negociação em um período",
    description="""Retorna os dias de negociação (ou de não-negociação) num período.

**Parâmetros**
- `start`: data inicial no formato YYYY-MM-DD
- `end`: data final no formato YYYY-MM-DD, maior ou igual a `start`
- `exclude`: se `true`, retorna os dias **sem** negociação; se `false` (padrão), os
  dias **com** negociação

**Restrições**
- O período deve estar inteiramente dentro da janela do calendário. Consulte
  `GET /v1/calendar-info` para os limites vigentes. Fora dela a resposta é 400 — a API
  não devolve resultado parcial em silêncio.
- O span máximo por requisição é limitado (`max_range_days`); períodos maiores são
  rejeitados com 400.
- Data mal formada responde 422.""",
    responses={
        200: examples_response(
            "Lista de datas obtida com sucesso",
            {
                "trading_days": {
                    "summary": "Dias de negociação",
                    "value": ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"],
                },
                "non_trading_days": {
                    "summary": "Dias sem negociação (exclude=true)",
                    "value": ["2026-09-05", "2026-09-06", "2026-09-07"],
                },
            },
        ),
        400: RESPONSE_RANGE_INVALID,
        503: RESPONSE_CALENDAR_UNAVAILABLE,
    },
)
async def get_trading_days(
    calendar: CalendarDep,
    settings: SettingsDep,
    # Tipar como `date` deixa o FastAPI validar e responder 422 para formato inválido,
    # em vez do parse manual que respondia 400 e aceitava datas como 2024-13-45.
    start: Annotated[date, Query(description="Data inicial (YYYY-MM-DD)")],
    end: Annotated[date, Query(description="Data final (YYYY-MM-DD)")],
    exclude: Annotated[
        bool,
        Query(description="Se true, retorna dias SEM negociação; se false, dias COM negociação"),
    ] = False,
) -> list[str]:
    """Lista dias de negociação (ou de não-negociação) num período."""
    _validate_range(calendar, start, end, settings.max_range_days)

    days = (
        calendar.non_sessions_in_range(start, end)
        if exclude
        else calendar.sessions_in_range(start, end)
    )
    return [day.isoformat() for day in days]
