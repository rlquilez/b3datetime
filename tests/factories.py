"""Construtores de dados de teste."""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.services.calendar_service import TradingCalendar

# Feriados da B3 em 2024 que caem em dia útil. Suficiente para exercitar a diferença
# entre "fim de semana", "feriado" e "fora da janela" sem construir o calendário real.
B3_HOLIDAYS_2024: tuple[date, ...] = (
    date(2024, 1, 1),  # Confraternização Universal
    date(2024, 2, 12),  # Carnaval
    date(2024, 2, 13),  # Carnaval
    date(2024, 3, 29),  # Sexta-feira Santa
    date(2024, 5, 1),  # Dia do Trabalho
    date(2024, 5, 30),  # Corpus Christi
    date(2024, 11, 15),  # Proclamação da República
    date(2024, 11, 20),  # Consciência Negra
    date(2024, 12, 25),  # Natal
)


def make_calendar(
    start: str = "2024-01-01",
    end: str = "2024-12-31",
    holidays: tuple[date, ...] = B3_HOLIDAYS_2024,
) -> TradingCalendar:
    """Calendário sintético: dias úteis do período menos os feriados informados.

    Construir um `TradingCalendar` direto do índice evita o custo do
    `exchange_calendars` — o router só toca a interface do `TradingCalendar`.
    """
    business_days = pd.bdate_range(start=start, end=end)
    kept = [ts for ts in business_days if ts.date() not in holidays]
    return TradingCalendar(
        pd.DatetimeIndex(kept),
        coverage_start=pd.Timestamp(start).date(),
        coverage_end=pd.Timestamp(end).date(),
    )


def make_empty_calendar() -> TradingCalendar:
    """Calendário sem nenhuma sessão, para exercitar o caminho de limites nulos."""
    return TradingCalendar(pd.DatetimeIndex([]))
