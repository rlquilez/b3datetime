"""Horários (``HH:MM``) e a decodificação do que vem do Redis.

* O padrão de horário aceita **exatamente** as 1440 strings ``HH:MM`` ASCII — nem uma a
  mais (o ``\\d`` Unicode do pydantic-core aceitava dígitos arábico-índicos), nem uma a
  menos;
* ``_as_str`` é a identidade sobre ``str`` e o inverso de ``encode`` sobre bytes UTF-8; bytes
  que não são UTF-8 viram ``InvalidUpstreamValueError`` (502), nunca um 500.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from b3datetime.routers.hours import TradingTime
from b3datetime.services.redis_service import InvalidUpstreamValueError, _as_str

VALIDOS = frozenset(f"{h:02d}:{m:02d}" for h in range(24) for m in range(60))

# Quase-horários: dois "dígitos", dois-pontos, dois "dígitos" — misturando ASCII com
# dígitos de outros sistemas (arábico-índico, devanágari, largura total).
# Bases Unicode: ASCII, arábico-índico (U+0660), devanágari (U+0966), largura total (U+FF10).
DIGITO = st.sampled_from(
    [chr(base + i) for base in (0x30, 0x660, 0x966, 0xFF10) for i in range(10)]
)
QUASE_HORARIOS = st.builds(lambda a, b, c, d: f"{a}{b}:{c}{d}", DIGITO, DIGITO, DIGITO, DIGITO)


def _aceito(valor: str) -> bool:
    try:
        TradingTime(time=valor)
    except ValidationError:
        return False
    return True


@given(st.integers(0, 23), st.integers(0, 59))
def test_todo_horario_valido_e_aceito(hora: int, minuto: int) -> None:
    assert _aceito(f"{hora:02d}:{minuto:02d}")


@given(st.one_of(QUASE_HORARIOS, st.text(max_size=8)))
def test_aceito_se_e_somente_se_hh_mm_ascii(valor: str) -> None:
    assert _aceito(valor) == (valor in VALIDOS)


# Só caracteres codificáveis em UTF-8 (exclui surrogates isolados).
@given(st.text(alphabet=st.characters(codec="utf-8")))
def test_as_str_e_identidade_sobre_str_e_inverso_de_encode(texto: str) -> None:
    assert _as_str(texto, "k") == texto
    assert _as_str(texto.encode("utf-8"), "k") == texto


@given(st.binary())
def test_bytes_ou_decodificam_ou_viram_valor_invalido(bruto: bytes) -> None:
    try:
        esperado: str | None = bruto.decode("utf-8")
    except UnicodeDecodeError:
        esperado = None
    if esperado is not None:
        assert _as_str(bruto, "k") == esperado
        return
    with pytest.raises(InvalidUpstreamValueError) as exc:
        _as_str(bruto, "k")
    assert exc.value.key == "k"
