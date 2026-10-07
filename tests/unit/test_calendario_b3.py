"""O oráculo de domínio usado pelo E2E e pela integração (``tests/e2e/calendario_b3.py``).

Um oráculo errado aprovaria um calendário errado: as regras são testadas aqui, por si
só, em toda execução — antes viviam dentro do E2E e só rodavam contra a imagem.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urljoin

import pytest

from tests.e2e.calendario_b3 import (
    CONSCIENCIA_NEGRA_DESDE,
    anos_atras,
    fechamentos_da_b3,
    pascoa,
    quarta_de_cinzas,
)


@pytest.mark.parametrize(
    ("ano", "esperado"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2019, date(2019, 4, 21)),  # coincide com Tiradentes
        (2008, date(2008, 3, 23)),  # uma das mais cedo do século
    ],
)
def test_pascoa_confere_com_datas_conhecidas(ano: int, esperado: date) -> None:
    assert pascoa(ano) == esperado


def test_moveis_derivam_da_pascoa() -> None:
    dias = fechamentos_da_b3(2024)
    assert dias["Carnaval (segunda)"] == date(2024, 2, 12)
    assert dias["Carnaval (terça)"] == date(2024, 2, 13)
    assert dias["Sexta-feira Santa"] == date(2024, 3, 29)
    assert dias["Corpus Christi"] == date(2024, 5, 30)
    assert quarta_de_cinzas(2024) == date(2024, 2, 14)
    assert quarta_de_cinzas(2024) - timedelta(days=1) == dias["Carnaval (terça)"]


@pytest.mark.parametrize("ano", [2020, 2023])
def test_consciencia_negra_so_fecha_a_partir_de_2024(ano: int) -> None:
    """A B3 abriu em 20/11 de 2020 e de 2023: a regra não pode valer para trás."""
    assert "Consciência Negra" not in fechamentos_da_b3(ano)
    assert fechamentos_da_b3(CONSCIENCIA_NEGRA_DESDE)["Consciência Negra"] == date(2024, 11, 20)


def test_anos_atras_trata_29_de_fevereiro_como_o_pandas() -> None:
    assert anos_atras(date(2024, 2, 29), 10) == date(2014, 2, 28)
    assert anos_atras(date(2024, 2, 29), 4) == date(2020, 2, 29)
    assert anos_atras(date(2026, 10, 7), 10) == date(2016, 10, 7)


def test_asset_de_pagina_e_resolvido_como_no_navegador() -> None:
    """``./static/x`` na página ``<base>/docs`` vira ``<base>/static/x``, com ou sem prefixo.

    É a premissa das páginas de documentação referenciarem tudo relativamente
    (``OPENAPI_RELATIVE_URL``): o navegador resolve contra a URL pública.
    """
    assert (
        urljoin("https://h/b3datetime/docs", "./static/a.css")
        == "https://h/b3datetime/static/a.css"
    )
    assert (
        urljoin("http://127.0.0.1:1234/docs", "./openapi.json")
        == "http://127.0.0.1:1234/openapi.json"
    )
