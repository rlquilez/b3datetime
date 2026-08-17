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

    def __init__(self, coverage_start: date | None, coverage_end: date | None) -> None:
        self.coverage_start = coverage_start
        self.coverage_end = coverage_end
        if coverage_start is None or coverage_end is None:
            msg = "O calendário está vazio e não cobre nenhum período."
        else:
            msg = (
                "Período fora da janela coberta pelo calendário "
                f"({coverage_start.isoformat()} a {coverage_end.isoformat()}). "
                "Consulte GET /v1/calendar-info para os limites vigentes."
            )
        super().__init__(msg)


class TradingCalendar:
    """Sessões de negociação, indexadas para consulta em tempo constante.

    A **janela de cobertura** é distinta da primeira e da última sessão. Um calendário
    construído a partir de 2024-01-01 cobre esse dia — o feriado de Confraternização —
    ainda que a primeira *sessão* seja 2024-01-02. Confundir os dois faria a API
    rejeitar com 400 um período que ela sabe responder, só porque começa num feriado.
    """

    def __init__(
        self,
        sessions: pd.DatetimeIndex,
        *,
        coverage_start: date | None = None,
        coverage_end: date | None = None,
    ) -> None:
        self._sessions = sessions
        # frozenset em vez de list: a checagem de pertinência do caminho `exclude=true`
        # era O(dias x sessoes), o que levava ~77 s para o range máximo.
        self._session_dates: frozenset[date] = frozenset(ts.date() for ts in sessions)
        # Lista ordenada mantida uma vez, para recorte por bisect em vez de reordenar
        # o frozenset a cada requisição.
        self._sorted_dates: list[date] = sorted(self._session_dates)
        self._first: date | None = self._sorted_dates[0] if self._sorted_dates else None
        self._last: date | None = self._sorted_dates[-1] if self._sorted_dates else None
        # Sem janela explícita, a cobertura degrada para o intervalo das sessões.
        self._coverage_start: date | None = coverage_start or self._first
        self._coverage_end: date | None = coverage_end or self._last

    @property
    def first_session(self) -> date | None:
        return self._first

    @property
    def last_session(self) -> date | None:
        return self._last

    @property
    def coverage(self) -> tuple[date | None, date | None]:
        """Intervalo de datas sobre o qual o calendário sabe responder."""
        return self._coverage_start, self._coverage_end

    @property
    def bounds(self) -> tuple[date | None, date | None]:
        """Alias de `coverage`, mantido para leitura nos endpoints."""
        return self.coverage

    def __len__(self) -> int:
        return len(self._session_dates)

    def covers(self, start: date, end: date) -> bool:
        """O período está inteiramente dentro da janela de cobertura?"""
        if self._coverage_start is None or self._coverage_end is None:
            return False
        return self._coverage_start <= start and end <= self._coverage_end

    def require_coverage(self, start: date, end: date) -> None:
        """Levanta `CalendarRangeOutOfBoundsError` se o período não for coberto."""
        if not self.covers(start, end):
            raise CalendarRangeOutOfBoundsError(self._coverage_start, self._coverage_end)

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

    # A cobertura é o intervalo pedido, não o das sessões: o primeiro dia da janela
    # pode ser feriado ou fim de semana, e ainda assim é respondível.
    coverage_start = pd.Timestamp(start).date()
    coverage_end = pd.Timestamp(end).date() if end is not None else None
    if coverage_end is None and len(sessions):
        coverage_end = sessions[-1].date()

    trading_calendar = TradingCalendar(
        sessions, coverage_start=coverage_start, coverage_end=coverage_end
    )
    logger.info(
        "Calendário %s construído: %d sessões; cobertura de %s a %s",
        settings.exchange_name,
        len(trading_calendar),
        coverage_start,
        coverage_end,
    )
    return trading_calendar
