"""Regras do calendário da B3 conhecidas de fora do código: o oráculo dos testes de domínio.

Funções puras, sem I/O, usadas pelo E2E (contra a imagem real) e pela integração (contra
o ``exchange_calendars`` real). Ficam fora de um ``test_*.py`` para serem importáveis sem
arrastar o ``pytestmark`` do E2E — e são testadas por si só em ``tests/unit``.
"""

from __future__ import annotations

from datetime import date, timedelta

# Sessões por ano no calendário BVMF de 2017 a 2026: de 245 a 251.
SESSOES_POR_ANO = range(240, 256)

# A Consciência Negra (20/11) é feriado nacional desde 2024; antes, a B3 abriu em 2020
# e em 2023 (em outros anos o dia caiu em fim de semana ou feriado municipal).
CONSCIENCIA_NEGRA_DESDE = 2024


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher, calendário gregoriano)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes, dia = divmod(h + m - 7 * n + 114, 31)
    return date(ano, mes, dia + 1)


def fechamentos_da_b3(ano: int) -> dict[str, date]:
    """Dias em que a B3 nunca abre: feriados nacionais, 24 e 31/12, e os móveis."""
    domingo_de_pascoa = pascoa(ano)
    dias = {
        "Confraternização": date(ano, 1, 1),
        "Tiradentes": date(ano, 4, 21),
        "Dia do Trabalho": date(ano, 5, 1),
        "Independência": date(ano, 9, 7),
        "Nossa Senhora Aparecida": date(ano, 10, 12),
        "Finados": date(ano, 11, 2),
        "Proclamação da República": date(ano, 11, 15),
        "Véspera de Natal": date(ano, 12, 24),
        "Natal": date(ano, 12, 25),
        "Último dia do ano": date(ano, 12, 31),
        "Carnaval (segunda)": domingo_de_pascoa - timedelta(days=48),
        "Carnaval (terça)": domingo_de_pascoa - timedelta(days=47),
        "Sexta-feira Santa": domingo_de_pascoa - timedelta(days=2),
        "Corpus Christi": domingo_de_pascoa + timedelta(days=60),
    }
    if ano >= CONSCIENCIA_NEGRA_DESDE:
        dias["Consciência Negra"] = date(ano, 11, 20)
    return dias


def quarta_de_cinzas(ano: int) -> date:
    """Quarta-feira de Cinzas: a B3 abre (à tarde), apesar de vir depois do Carnaval."""
    return pascoa(ano) - timedelta(days=46)


def anos_atras(dia: date, anos: int) -> date:
    """Mesma data ``anos`` antes; 29/02 vira 28/02, como o DateOffset do pandas."""
    try:
        return dia.replace(year=dia.year - anos)
    except ValueError:
        return dia.replace(year=dia.year - anos, day=28)
