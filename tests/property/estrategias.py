"""Estratégias do Hypothesis compartilhadas pelos testes de propriedade."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from hypothesis import strategies as st

from b3datetime.services.calendar_service import TradingCalendar

# Datas num intervalo amplo o bastante para pegar viradas de ano, bissextos e meses curtos.
DATAS = st.dates(min_value=date(2000, 1, 1), max_value=date(2040, 12, 31))


@st.composite
def calendarios(draw: st.DrawFn, *, max_dias: int = 120) -> TradingCalendar:
    """Um ``TradingCalendar`` qualquer: janela de cobertura e sessões arbitrárias dentro dela.

    As sessões não seguem regra nenhuma (nem dia útil): as propriedades do calendário não
    podem depender de a bolsa abrir de segunda a sexta.
    """
    inicio = draw(DATAS)
    dias = draw(st.integers(min_value=0, max_value=max_dias))
    janela = [inicio + timedelta(days=i) for i in range(dias + 1)]
    sessoes = draw(st.lists(st.sampled_from(janela), unique=True)) if janela else []
    return TradingCalendar(
        pd.DatetimeIndex([pd.Timestamp(d) for d in sessoes]),
        coverage_start=janela[0],
        coverage_end=janela[-1],
    )
