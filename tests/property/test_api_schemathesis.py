"""Fuzzing da API inteira a partir do próprio contrato OpenAPI (Schemathesis + Hypothesis).

Para cada operação publicada, o Schemathesis gera requisições — válidas e inválidas segundo
o schema — e confere cada resposta contra o contrato: nenhum 5xx, todo status e todo
content-type documentados, corpo conforme o schema da resposta, entrada inválida rejeitada
com 4xx, entrada válida aceita, método não suportado respondido com 405 e ``Allow``.

Em processo, sobre a app real: só o lifespan é trocado por um que injeta os dublês (Redis
falso já semeado e um calendário sintético de 2000 a 2040), para o fuzzing medir a API e
não o Redis de quem roda o teste. Marcado ``api_fuzz``: é o único teste que exercita todas
as rotas a cada exemplo, por isso a mutação o deixa de fora (ver ``[tool.mutmut]``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import fakeredis.aioredis
import pytest
import schemathesis
from fastapi import FastAPI
from schemathesis.python.asgi import shutdown_lifespans
from schemathesis.specs.openapi.checks import positive_data_acceptance

from b3datetime.config import Settings
from b3datetime.main import create_app
from b3datetime.services.redis_service import RedisService
from tests.factories import make_calendar

pytestmark = [
    pytest.mark.api_fuzz,
    # Vazamento do próprio Schemathesis (4.29): o _Lifespan que ele mantém para a app cria
    # dois pares de memory streams do anyio e nunca os fecha; ao ser coletado, o anyio emite
    # ResourceWarning — que o `filterwarnings = error` da suíte faria virar erro. O filtro é
    # restrito a este módulo e a essa mensagem exata.
    pytest.mark.filterwarnings("ignore:Unclosed <MemoryObject(Receive|Send)Stream:ResourceWarning"),
]


def _app_com_dubles() -> FastAPI:
    settings = Settings(_env_file=None)
    app = create_app(settings)

    @asynccontextmanager
    async def lifespan_de_teste(app_: FastAPI) -> AsyncIterator[None]:
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await redis.set(settings.redis_key_open, "10:00")
        await redis.set(settings.redis_key_close, "17:00")
        app_.state.redis_service = RedisService(settings, client_factory=lambda: redis)
        # Janela larga, cobrindo "hoje": /v1/is-trading-day responde 200, não 503.
        app_.state.calendar = make_calendar("2000-01-01", "2040-12-31", holidays=())
        yield
        await redis.aclose()

    app.router.lifespan_context = lifespan_de_teste
    return app


@pytest.fixture(scope="module")
def contrato() -> Iterator[schemathesis.BaseSchema]:
    yield schemathesis.openapi.from_asgi("/openapi.json", _app_com_dubles())
    # O Schemathesis mantém o lifespan da app aberto até o fim do processo; encerrá-lo aqui
    # roda o shutdown (fecha o Redis falso) e fecha os streams — sem isso sobra um
    # ResourceWarning, que o `filterwarnings = error` da suíte transforma em erro.
    shutdown_lifespans()


schema = schemathesis.pytest.from_fixture("contrato")


@schema.parametrize()
def test_api_cumpre_o_proprio_contrato(case: schemathesis.Case[Any]) -> None:
    # /v1/trading-days responde 400 (documentado) a períodos válidos pelo schema mas
    # inválidos pelo domínio: invertidos, acima do limite ou fora da janela. A aceitação
    # de dado "positivo" não vale ali — essa regra é provada à parte, pelo oráculo de
    # _validate_range em test_calendario.py.
    excluidos = [positive_data_acceptance] if case.operation.path == "/v1/trading-days" else []
    case.call_and_validate(excluded_checks=excluidos)
