"""Calendário de negociação da B3, encapsulando o `exchange_calendars`.

O calendário é construído sobre uma **janela móvel** (por padrão, dez anos para trás a
partir de hoje). Os limites reais são sempre lidos do índice de sessões construído, e
nunca de uma constante — foi justamente a divergência entre uma constante (2006) e a
janela real que fazia a API responder `[]` ou "todos os dias são feriado" com HTTP 200
para períodos fora da cobertura.
"""

from __future__ import annotations

import logging
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

import exchange_calendars as xcals
import pandas as pd

from src.config import Settings

logger = logging.getLogger(__name__)


class CalendarUnavailableError(RuntimeError):
    """O calendário não pôde ser construído."""


class CalendarRangeOutOfBoundsError(ValueError):
    """O período pedido não está inteiramente coberto pelo calendário."""

    def __init__(self, first_session: date | None, last_session: date | None) -> None:
        self.first_session = first_session
        self.last_session = last_session
        if first_session is None or last_session is None:
            msg = "O calendário está vazio e não cobre nenhum período."
        else:
            msg = (
                "Período fora da janela coberta pelo calendário "
                f"({first_session.isoformat()} a {last_session.isoformat()}). "
                "Consulte GET /v1/calendar-info para os limites vigentes."
            )
        super().__init__(msg)


class TradingCalendar:
    """Sessões de negociação, indexadas para consulta em tempo constante."""

    def __init__(self, sessions: pd.DatetimeIndex) -> None:
        self._sessions = sessions
        # frozenset em vez de list: a checagem de pertinência do caminho `exclude=true`
        # era O(dias x sessoes), o que levava ~77 s para o range máximo.
        self._session_dates: frozenset[date] = frozenset(ts.date() for ts in sessions)
        # Lista ordenada mantida uma vez, para recorte por bisect em vez de reordenar
        # o frozenset a cada requisição.
        self._sorted_dates: list[date] = sorted(self._session_dates)
        self._first: date | None = self._sorted_dates[0] if self._sorted_dates else None
        self._last: date | None = self._sorted_dates[-1] if self._sorted_dates else None

    @property
    def first_session(self) -> date | None:
        return self._first

    @property
    def last_session(self) -> date | None:
        return self._last

    @property
    def bounds(self) -> tuple[date | None, date | None]:
        return self._first, self._last

    def __len__(self) -> int:
        return len(self._session_dates)

    def covers(self, start: date, end: date) -> bool:
        """O período está inteiramente dentro da janela do calendário?"""
        if self._first is None or self._last is None:
            return False
        return self._first <= start and end <= self._last

    def require_coverage(self, start: date, end: date) -> None:
        """Levanta `CalendarRangeOutOfBoundsError` se o período não for coberto."""
        if not self.covers(start, end):
            raise CalendarRangeOutOfBoundsError(self._first, self._last)

    def is_session(self, day: date) -> bool:
        """`day` é dia de negociação? Só é significativo dentro da janela."""
        return day in self._session_dates

    def sessions_in_range(self, start: date, end: date) -> list[date]:
        """Dias de negociação no período, inclusivo nas duas pontas."""
        lo = bisect_left(self._sorted_dates, start)
        hi = bisect_right(self._sorted_dates, end)
        return self._sorted_dates[lo:hi]

    def non_sessions_in_range(self, start: date, end: date) -> list[date]:
        """Dias sem negociação no período — o complemento exato de `sessions_in_range`."""
        out: list[date] = []
        current = start
        while current <= end:
            if current not in self._session_dates:
                out.append(current)
            current += timedelta(days=1)
        return out


def build_bvmf_calendar(
    settings: Settings,
    *,
    start: date | str | None = None,
    end: date | str | None = None,
) -> TradingCalendar:
    """Constrói o calendário da bolsa configurada.

    Sem `start`, usa a janela móvel de `settings.calendar_start_offset_years` anos.
    Esse cálculo e o acesso direto a `.sessions` (em vez de `sessions_in_range`) são
    deliberados: contornam erros de `parse_date`/`DateOutOfBounds` do exchange_calendars
    — ver commits 2b4bc6d..ebd0a07. Não "simplifique" sem reproduzir aquelas falhas.

    `start`/`end` explícitos existem para os testes, que precisam de uma janela pequena.
    """
    if start is None:
        now = pd.Timestamp.now(tz=settings.timezone).normalize().tz_localize(None)
        start = now - pd.DateOffset(years=settings.calendar_start_offset_years)

    try:
        calendar = xcals.get_calendar(settings.exchange_name, start=start, end=end)
        sessions = calendar.sessions
    except Exception as exc:  # qualquer falha de construção vira indisponibilidade
        raise CalendarUnavailableError(
            f"Erro ao carregar o calendário {settings.exchange_name}: {exc}"
        ) from exc

    trading_calendar = TradingCalendar(sessions)
    logger.info(
        "Calendário %s construído: %d sessões, de %s a %s",
        settings.exchange_name,
        len(trading_calendar),
        trading_calendar.first_session,
        trading_calendar.last_session,
    )
    return trading_calendar
