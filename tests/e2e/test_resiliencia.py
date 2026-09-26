"""Recuperação sem restart: o Redis que só sobe depois da API.

É o invariante "o cliente Redis nunca vira ``None``" provado no container real. O código
antigo descartava o cliente quando o ping inicial falhava e a API respondia 503 para
sempre, mesmo depois de o Redis voltar. Os testes de unidade provam isso com
``fakeredis``; aqui é com a imagem, a rede do Docker e um Redis de verdade.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.e2e.conftest import HORARIOS, Execucao
from tests.e2e.contrato import Contrato

pytestmark = pytest.mark.e2e

PRAZO_S = 45


def test_redis_que_sobe_depois_e_recuperado_sem_restart(
    execucao: Execucao, contrato: Contrato
) -> None:
    amb = execucao.ambiente("redis_tardio")
    orquestrador = execucao.orquestrador
    assert orquestrador is not None

    fora = amb.http.get("/v1/hours")
    assert fora.status_code == 503
    contrato.validar("GET", "/v1/hours", fora)
    assert amb.http.get("/v1/health").json()["status"] == "unhealthy"

    # O nome é o que o app espera em REDIS_URL_ENV; o DNS do Docker passa a resolvê-lo.
    orquestrador.subir_redis("redis-tardio-db")

    prazo = time.monotonic() + PRAZO_S
    health = amb.http.get("/v1/health")
    while health.status_code != httpx.codes.OK and time.monotonic() < prazo:
        time.sleep(0.5)
        health = amb.http.get("/v1/health")

    assert health.status_code == 200, f"sem recuperação em {PRAZO_S} s: {health.text}"
    assert health.json()["status"] == "healthy"
    horarios = amb.http.get("/v1/hours")
    assert horarios.status_code == 200
    assert horarios.json() == HORARIOS
