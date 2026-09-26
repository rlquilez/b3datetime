"""Ambientes da suíte E2E.

Dois modos, escolhidos por variável de ambiente:

- ``E2E_IMAGE=<imagem>``: sobe a imagem em containers, com Redis real e o calendário
  BVMF real, nas quatro configurações de ``_subir_ambientes``. É o modo do job ``e2e`` do
  CI, e nele nada pode ser pulado.
- ``E2E_BASE_URL=<url>``: roda contra uma API já no ar (ex.: produção) só o que lê. O
  que depende de controlar o Redis ou dos outros ambientes é pulado com o motivo.

O marcador ``e2e`` fica fora da execução padrão do pytest (``-m "not e2e"`` no
``addopts``): a suíte roda com ``pytest -m e2e tests/e2e``.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest
import redis

from tests.e2e.contrato import Contrato

PREFIXO = "/b3datetime"
IMAGEM_REDIS = "redis:7.4-alpine"
CHAVE_ABERTURA = "b3:trading:hours:open"
CHAVE_FECHAMENTO = "b3:trading:hours:close"
HORARIOS = {"open": "10:00", "close": "17:00"}
TZ = ZoneInfo("America/Sao_Paulo")
PRAZO_PRONTO_S = 120


def hoje() -> date:
    """Hoje no fuso da API."""
    return datetime.now(TZ).date()


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    """Executa o Docker CLI. Os argumentos vêm só desta suíte, nunca de entrada externa."""
    comando = ["docker", *args]
    return subprocess.run(comando, capture_output=True, text=True, check=False)  # noqa: S603


def docker(*args: str, check: bool = True) -> str:
    """Saída de um comando do Docker CLI; com ``check``, falha se o comando falhar."""
    r = _docker(*args)
    if check and r.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} falhou: {r.stderr.strip()}")
    return r.stdout.strip()


@dataclass
class Ambiente:
    """Uma instância da API sob teste."""

    nome: str
    http: httpx.Client
    prefixo: str
    # Cliente do Redis do ambiente, para trocar chaves; só em containers.
    redis: redis.Redis | None = None
    # Horários semeados, quando conhecidos (em produção, não são).
    horarios: dict[str, str] | None = None
    container: str | None = None


@dataclass
class Orquestrador:
    """Rede e containers de uma execução, com nomes únicos por execução."""

    imagem: str
    sufixo: str = field(default_factory=lambda: secrets.token_hex(4))
    containers: list[str] = field(default_factory=list)

    @property
    def rede(self) -> str:
        return f"e2e-{self.sufixo}"

    def nome(self, papel: str) -> str:
        return f"e2e-{papel}-{self.sufixo}"

    def subir(self, papel: str, imagem: str, *opcoes: str, porta: int) -> str:
        nome = self.nome(papel)
        publicar = ["-p", f"127.0.0.1::{porta}"]
        docker("run", "-d", "--name", nome, "--network", self.rede, *publicar, *opcoes, imagem)
        self.containers.append(nome)
        return nome

    def porta(self, nome: str, porta: int) -> int:
        return int(docker("port", nome, f"{porta}/tcp").splitlines()[0].rsplit(":", 1)[1])

    def subir_app(self, papel: str, **env: str) -> str:
        opcoes = [x for k, v in {"ROOT_PATH": PREFIXO, **env}.items() for x in ("-e", f"{k}={v}")]
        return self.subir(papel, self.imagem, *opcoes, porta=8000)

    def subir_redis(self, papel: str) -> str:
        """Sobe um Redis, espera o PONG e semeia os horários."""
        nome = self.subir(papel, IMAGEM_REDIS, porta=6379)
        prazo = time.monotonic() + 30
        while docker("exec", nome, "redis-cli", "ping", check=False) != "PONG":
            if time.monotonic() > prazo:
                raise RuntimeError(f"{nome} não respondeu PONG em 30 s")
            time.sleep(0.5)
        docker("exec", nome, "redis-cli", "SET", CHAVE_ABERTURA, HORARIOS["open"])
        docker("exec", nome, "redis-cli", "SET", CHAVE_FECHAMENTO, HORARIOS["close"])
        return nome

    def logs(self, nome: str) -> str:
        r = _docker("logs", "--tail", "80", nome)
        return r.stdout + r.stderr

    def encerrar(self) -> None:
        for nome in self.containers:
            docker("rm", "-f", nome, check=False)
        docker("network", "rm", self.rede, check=False)


@dataclass
class Execucao:
    """Ambientes disponíveis nesta execução e, em containers, o orquestrador."""

    ambientes: dict[str, Ambiente]
    orquestrador: Orquestrador | None = None

    def ambiente(self, nome: str) -> Ambiente:
        if nome not in self.ambientes:
            pytest.skip(f"o ambiente {nome!r} só existe com E2E_IMAGE (containers)")
        return self.ambientes[nome]


def _aguardar(amb: Ambiente, *, saudavel: bool) -> None:
    """Espera a API responder — e, se pedido, responder 200 no health."""
    prazo = time.monotonic() + PRAZO_PRONTO_S
    ultimo = "sem resposta"
    while time.monotonic() < prazo:
        try:
            r = amb.http.get("/v1/health")
        except httpx.TransportError as exc:
            ultimo = repr(exc)
        else:
            if not saudavel or r.status_code == httpx.codes.OK:
                return
            ultimo = f"{r.status_code} {r.text}"
        time.sleep(1)
    raise RuntimeError(f"ambiente {amb.nome} não ficou pronto em {PRAZO_PRONTO_S} s: {ultimo}")


def _subir_ambientes(orq: Orquestrador) -> dict[str, Ambiente]:
    docker("network", "create", orq.rede)
    redis_principal = orq.subir_redis("redis")
    redis_url = f"redis://{redis_principal}:6379"
    # Os quatro apps sobem juntos: cada um constrói o calendário em alguns segundos.
    apps = {
        # Como em produção: Redis real semeado e ROOT_PATH, com o caminho chegando sem o
        # prefixo (Kong com strip_path: true).
        "principal": orq.subir_app("principal", REDIS_URL_ENV=redis_url),
        # Porta fechada: 503 nos horários e health unhealthy.
        "sem_redis": orq.subir_app(
            "sem-redis", REDIS_URL_ENV="redis://127.0.0.1:1", REDIS_SOCKET_TIMEOUT_SECONDS="1"
        ),
        # Bolsa inexistente: o calendário não é construído e as datas respondem 503.
        "sem_calendario": orq.subir_app(
            "sem-calendario", REDIS_URL_ENV=redis_url, EXCHANGE_NAME="INEXISTENTE"
        ),
        # O Redis deste só sobe durante o teste de recuperação.
        "redis_tardio": orq.subir_app(
            "redis-tardio",
            REDIS_URL_ENV=f"redis://{orq.nome('redis-tardio-db')}:6379",
            REDIS_RECONNECT_INTERVAL_SECONDS="1",
            REDIS_SOCKET_TIMEOUT_SECONDS="1",
        ),
    }
    controle = redis.Redis(
        host="127.0.0.1", port=orq.porta(redis_principal, 6379), decode_responses=True
    )
    ambientes = {
        papel: Ambiente(
            nome=papel,
            http=httpx.Client(base_url=f"http://127.0.0.1:{orq.porta(nome, 8000)}", timeout=30),
            prefixo=PREFIXO,
            redis=controle if papel == "principal" else None,
            horarios=HORARIOS if papel == "principal" else None,
            container=nome,
        )
        for papel, nome in apps.items()
    }
    for amb in ambientes.values():
        _aguardar(amb, saudavel=amb.nome == "principal")
    return ambientes


@pytest.fixture(scope="session")
def execucao(request: pytest.FixtureRequest) -> Iterator[Execucao]:
    base_externa = os.environ.get("E2E_BASE_URL")
    if base_externa:
        prefixo = urlsplit(base_externa).path.rstrip("/")
        with httpx.Client(base_url=base_externa, timeout=30) as http:
            yield Execucao({"principal": Ambiente("externo", http, prefixo)})
        return

    imagem = os.environ.get("E2E_IMAGE")
    if not imagem:
        pytest.skip("defina E2E_IMAGE (imagem a subir) ou E2E_BASE_URL (API já no ar)")

    orq = Orquestrador(imagem)
    ambientes: dict[str, Ambiente] = {}
    try:
        ambientes = _subir_ambientes(orq)
        yield Execucao(ambientes, orq)
    finally:
        if request.session.testsfailed or not ambientes:
            for nome in orq.containers:
                print(f"\n--- docker logs {nome} ---\n{orq.logs(nome)}", file=sys.__stderr__)
        for amb in ambientes.values():
            amb.http.close()
            if amb.redis is not None:
                amb.redis.close()
        orq.encerrar()


@pytest.fixture(scope="session")
def principal(execucao: Execucao) -> Ambiente:
    return execucao.ambiente("principal")


@pytest.fixture(scope="session")
def contrato(principal: Ambiente) -> Contrato:
    """O OpenAPI servido pela instância sob teste. Todas sobem da mesma imagem."""
    r = principal.http.get("/openapi.json")
    assert r.status_code == httpx.codes.OK, r.text
    return Contrato(r.json())
