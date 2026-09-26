"""Toda resposta documentada de toda operação publicada, validada contra o contrato.

``CASOS`` tem ao menos um caso por par (operação, código) do ``/openapi.json`` servido,
e ``test_cobertura_de_100_por_cento_do_contrato`` exige que os dois conjuntos sejam
**iguais**: uma rota ou um código novo publicado sem caso E2E reprova o pipeline, e um
caso para um código que o contrato não documenta também.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from tests.e2e.conftest import CHAVE_ABERTURA, CHAVE_FECHAMENTO, Ambiente, Execucao, hoje
from tests.e2e.contrato import Contrato

pytestmark = pytest.mark.e2e

Params = dict[str, str] | Callable[[Ambiente], dict[str, str]]
Verificacao = Callable[[httpx.Response, Ambiente], None]


def _gravar(amb: Ambiente, valores: dict[str, str | None]) -> None:
    """Grava as chaves no Redis do ambiente; ``None`` apaga a chave."""
    assert amb.redis is not None
    for chave, valor in valores.items():
        if valor is None:
            amb.redis.delete(chave)
        else:
            amb.redis.set(chave, valor)


@contextmanager
def _redis_com(amb: Ambiente, valores: dict[str, str | None]) -> Iterator[None]:
    """Troca chaves do Redis do ambiente e restaura os valores originais na saída."""
    assert amb.redis is not None
    originais = {chave: amb.redis.get(chave) for chave in valores}
    _gravar(amb, valores)
    try:
        yield
    finally:
        _gravar(amb, originais)


def _com(valores: dict[str, str | None]) -> Callable[[Ambiente], AbstractContextManager[None]]:
    return lambda amb: _redis_com(amb, valores)


@dataclass(frozen=True)
class Caso:
    caminho: str
    status: int
    descricao: str
    ambiente: str = "principal"
    params: Params | None = None
    preparo: Callable[[Ambiente], AbstractContextManager[None]] | None = None
    verificar: Verificacao | None = None

    @property
    def id(self) -> str:
        return f"{self.caminho} {self.status} {self.descricao}"


# --- verificações específicas de cada caso ------------------------------------------


def _detalhe(r: httpx.Response) -> dict[str, Any]:
    detalhe = r.json()["detail"]
    assert isinstance(detalhe, dict)
    return detalhe


def _horarios_semeados(r: httpx.Response, amb: Ambiente) -> None:
    if amb.horarios is not None:
        assert r.json() == amb.horarios


def _horario(campo: str) -> Verificacao:
    def verificar(r: httpx.Response, amb: Ambiente) -> None:
        if amb.horarios is not None:
            assert r.json() == {"time": amb.horarios[campo]}

    return verificar


def _chave_ausente(chave: str) -> Verificacao:
    def verificar(r: httpx.Response, _: Ambiente) -> None:
        assert _detalhe(r)["key"] == chave

    return verificar


def _redis_indisponivel(r: httpx.Response, _: Ambiente) -> None:
    detalhe = _detalhe(r)
    assert detalhe["key"] in {CHAVE_ABERTURA, CHAVE_FECHAMENTO}
    assert "cache_age_seconds" not in detalhe  # nunca houve cache neste ambiente


def _calendario_indisponivel(r: httpx.Response, _: Ambiente) -> None:
    assert _detalhe(r)["message"] == "Calendário de negociação indisponível"


def _mensagem_contem(trecho: str) -> Verificacao:
    def verificar(r: httpx.Response, _: Ambiente) -> None:
        assert trecho in _detalhe(r)["message"]

    return verificar


def _parametro_invalido(nome: str) -> Verificacao:
    def verificar(r: httpx.Response, _: Ambiente) -> None:
        assert any(nome in erro["loc"] for erro in r.json()["detail"]), r.text

    return verificar


def _info(amb: Ambiente) -> dict[str, Any]:
    info = amb.http.get("/v1/calendar-info").json()
    assert isinstance(info, dict)
    return info


def _dezembro_do_ano_passado(_: Ambiente) -> dict[str, str]:
    ano = hoje().year - 1
    return {"start": f"{ano}-12-01", "end": f"{ano}-12-31"}


def _dias_de_dezembro(r: httpx.Response, _: Ambiente) -> None:
    ano = hoje().year - 1
    dias = [date.fromisoformat(d) for d in r.json()]
    assert dias, "dezembro sem nenhum pregão"
    assert all(d.year == ano and d.month == 12 and d.weekday() < 5 for d in dias)
    assert not {date(ano, 12, 24), date(ano, 12, 25), date(ano, 12, 31)} & set(dias)


def _span_acima_do_maximo(amb: Ambiente) -> dict[str, str]:
    fim = date(hoje().year - 1, 12, 31)
    return {
        "start": (fim - timedelta(days=_info(amb)["max_range_days"] + 1)).isoformat(),
        "end": fim.isoformat(),
    }


def _antes_da_janela(amb: Ambiente) -> dict[str, str]:
    inicio = date.fromisoformat(_info(amb)["coverage_start"])
    return {
        "start": (inicio - timedelta(days=1)).isoformat(),
        "end": (inicio + timedelta(days=10)).isoformat(),
    }


def _info_valido(r: httpx.Response, _: Ambiente) -> None:
    corpo = r.json()
    assert corpo["exchange"] == "BVMF"
    assert corpo["coverage_start"] <= corpo["first_session"] <= corpo["last_session"]
    assert corpo["last_session"] == corpo["coverage_end"]


def _hoje(r: httpx.Response, _: Ambiente) -> None:
    assert date.fromisoformat(r.json()["date"]) in {hoje() - timedelta(days=1), hoje()}


def _saudavel(r: httpx.Response, _: Ambiente) -> None:
    corpo = r.json()
    assert (corpo["status"], corpo["redis_status"]) == ("healthy", "connected")
    assert corpo["calendar"]["available"] is True


def _unhealthy_sem_redis(r: httpx.Response, _: Ambiente) -> None:
    corpo = r.json()
    assert (corpo["status"], corpo["redis_status"]) == ("unhealthy", "disconnected")
    assert set(corpo["calendar"]) == {
        "available",
        "first_session",
        "last_session",
        "sessions_count",
    }


def _unhealthy_sem_calendario(r: httpx.Response, _: Ambiente) -> None:
    corpo = r.json()
    assert (corpo["status"], corpo["redis_status"]) == ("unhealthy", "connected")
    assert corpo["calendar"] == {"available": False}


# --- a tabela ---------------------------------------------------------------------------

_HORARIOS = [
    ("/v1/hours", CHAVE_ABERTURA, _horarios_semeados),
    ("/v1/hours/open", CHAVE_ABERTURA, _horario("open")),
    ("/v1/hours/close", CHAVE_FECHAMENTO, _horario("close")),
]

CASOS: list[Caso] = [
    Caso("/", 200, "metadados"),
    *[
        caso
        for caminho, chave, sucesso in _HORARIOS
        for caso in (
            Caso(caminho, 200, "valores do Redis", verificar=sucesso),
            Caso(
                caminho,
                404,
                "chave ausente",
                preparo=_com({chave: None}),
                verificar=_chave_ausente(chave),
            ),
            Caso(caminho, 502, "valor fora de HH:MM", preparo=_com({chave: "25:99"})),
            Caso(
                caminho,
                503,
                "Redis fora e sem cache",
                ambiente="sem_redis",
                verificar=_redis_indisponivel,
            ),
        )
    ],
    Caso("/v1/calendar-info", 200, "limites", verificar=_info_valido),
    Caso(
        "/v1/calendar-info",
        503,
        "sem calendário",
        ambiente="sem_calendario",
        verificar=_calendario_indisponivel,
    ),
    Caso("/v1/is-trading-day", 200, "hoje", verificar=_hoje),
    Caso(
        "/v1/is-trading-day",
        503,
        "sem calendário",
        ambiente="sem_calendario",
        verificar=_calendario_indisponivel,
    ),
    Caso(
        "/v1/trading-days",
        200,
        "dezembro do ano passado",
        params=_dezembro_do_ano_passado,
        verificar=_dias_de_dezembro,
    ),
    Caso(
        "/v1/trading-days",
        400,
        "fim antes do início",
        params={"start": "2025-01-31", "end": "2025-01-02"},
        verificar=_mensagem_contem("maior ou igual"),
    ),
    Caso(
        "/v1/trading-days",
        400,
        "span acima do máximo",
        params=_span_acima_do_maximo,
        verificar=_mensagem_contem("excede o máximo"),
    ),
    Caso(
        "/v1/trading-days",
        400,
        "antes da janela",
        params=_antes_da_janela,
        verificar=_mensagem_contem("fora da janela"),
    ),
    Caso(
        "/v1/trading-days",
        422,
        "data impossível",
        params={"start": "2025-13-01", "end": "2025-12-31"},
        verificar=_parametro_invalido("start"),
    ),
    Caso(
        "/v1/trading-days",
        422,
        "sem a data final",
        params={"start": "2025-01-02"},
        verificar=_parametro_invalido("end"),
    ),
    Caso(
        "/v1/trading-days",
        503,
        "sem calendário",
        ambiente="sem_calendario",
        params={"start": "2025-01-02", "end": "2025-01-31"},
        verificar=_calendario_indisponivel,
    ),
    Caso("/v1/health", 200, "healthy", verificar=_saudavel),
    Caso("/v1/health", 503, "Redis fora", ambiente="sem_redis", verificar=_unhealthy_sem_redis),
    Caso(
        "/v1/health",
        503,
        "sem calendário",
        ambiente="sem_calendario",
        verificar=_unhealthy_sem_calendario,
    ),
]


@pytest.mark.parametrize("caso", CASOS, ids=lambda caso: caso.id)
def test_resposta_segue_o_contrato(caso: Caso, execucao: Execucao, contrato: Contrato) -> None:
    amb = execucao.ambiente(caso.ambiente)
    if caso.preparo is not None and amb.redis is None:
        pytest.skip("exige controlar o Redis do ambiente (E2E_IMAGE)")
    params = caso.params(amb) if callable(caso.params) else caso.params

    with caso.preparo(amb) if caso.preparo else nullcontext():
        r = amb.http.get(caso.caminho, params=params)

    assert r.status_code == caso.status, r.text
    assert r.headers["content-type"].startswith("application/json")
    contrato.validar("GET", caso.caminho, r)
    if caso.verificar is not None:
        caso.verificar(r, amb)


def test_cobertura_de_100_por_cento_do_contrato(contrato: Contrato) -> None:
    """Cada resposta documentada de cada operação publicada tem caso — e só elas."""
    documentados = contrato.pares()
    cobertos = {("GET", caso.caminho, str(caso.status)) for caso in CASOS}
    assert documentados, "o contrato servido não publica nenhuma operação"
    assert not documentados - cobertos, f"sem caso E2E: {sorted(documentados - cobertos)}"
    assert not cobertos - documentados, f"não documentados: {sorted(cobertos - documentados)}"
