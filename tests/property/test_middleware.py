"""``RootPathPrefixMiddleware`` sobre prefixos e caminhos gerados.

O contrato ASGI que o Starlette passou a exigir: ``scope["path"]`` sempre começa com
``scope["root_path"]``. Para qualquer prefixo e caminho:

* depois do middleware, o caminho começa com o prefixo (é o que faz ``/static`` funcionar
  atrás do Kong com ``strip_path: true``);
* um caminho que já traz o prefixo (``strip_path: false``) passa intacto — aplicar duas
  vezes não duplica nada;
* ``raw_path`` acompanha ``path``;
* sem prefixo, ou em ``lifespan``, nada muda.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from starlette.types import Message, Receive, Scope, Send

from b3datetime.middleware import RootPathPrefixMiddleware

SEGMENTO = st.from_regex(r"[a-z0-9][a-z0-9._-]{0,11}", fullmatch=True)
PREFIXOS = st.lists(SEGMENTO, min_size=1, max_size=3).map(lambda s: "/" + "/".join(s))
CAMINHOS = st.lists(SEGMENTO, max_size=4).map(lambda s: "/" + "/".join(s))


def _passar(scope: dict[str, Any]) -> dict[str, Any]:
    visto: dict[str, Any] = {}

    async def app(sc: Scope, _receive: Receive, _send: Send) -> None:
        visto.update(sc)

    async def receive() -> Message:
        return {"type": "http.request"}

    async def send(_message: Message) -> None:
        return None

    asyncio.run(RootPathPrefixMiddleware(app)(scope, receive, send))
    return visto


def _scope(root_path: str, path: str) -> dict[str, Any]:
    return {"type": "http", "root_path": root_path, "path": path, "raw_path": path.encode()}


@given(PREFIXOS, CAMINHOS)
def test_caminho_sempre_comeca_com_o_prefixo(prefixo: str, caminho: str) -> None:
    saida = _passar(_scope(prefixo, caminho))
    assert saida["path"] == prefixo or saida["path"].startswith(prefixo + "/")
    assert saida["raw_path"] == saida["path"].encode()


@given(PREFIXOS, CAMINHOS)
def test_ja_prefixado_passa_intacto_e_e_idempotente(prefixo: str, caminho: str) -> None:
    uma_vez = _passar(_scope(prefixo, caminho))
    duas_vezes = _passar(dict(uma_vez))
    assert duas_vezes["path"] == uma_vez["path"]
    assert duas_vezes["raw_path"] == uma_vez["raw_path"]


@given(CAMINHOS)
def test_sem_prefixo_nada_muda(caminho: str) -> None:
    assert _passar(_scope("", caminho))["path"] == caminho


@given(PREFIXOS)
def test_lifespan_passa_intacto(prefixo: str) -> None:
    scope = {"type": "lifespan", "root_path": prefixo}
    assert _passar(dict(scope)) == scope
