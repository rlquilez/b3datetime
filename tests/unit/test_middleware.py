"""RootPathPrefixMiddleware: recompõe o prefixo removido pelo proxy no scope ASGI."""

from __future__ import annotations

from typing import Any

import pytest

from src.middleware import RootPathPrefixMiddleware


async def _run(scope: dict[str, Any]) -> dict[str, Any]:
    """Executa o middleware sobre um app fake e devolve o scope que ele recebeu."""
    seen: dict[str, Any] = {}

    async def inner(sc: dict[str, Any], _receive: Any, _send: Any) -> None:
        seen.update(sc)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def send(_message: dict[str, Any]) -> None:
        return None

    await RootPathPrefixMiddleware(inner)(scope, receive, send)
    return seen


@pytest.mark.parametrize(
    ("root_path", "path", "esperado"),
    [
        pytest.param("", "/docs", "/docs", id="sem-root_path"),
        pytest.param("/p", "/docs", "/p/docs", id="prefixo-removido-pelo-proxy"),
        pytest.param("/p", "/p/docs", "/p/docs", id="prefixo-ja-presente"),
        pytest.param("/p", "/p", "/p", id="path-igual-ao-prefixo"),
        pytest.param("/p", "/pdocs", "/p/pdocs", id="prefixo-so-como-substring"),
    ],
)
async def test_path_passa_a_comecar_com_root_path(root_path: str, path: str, esperado: str) -> None:
    scope = {"type": "http", "root_path": root_path, "path": path, "raw_path": path.encode()}
    seen = await _run(scope)
    assert seen["path"] == esperado
    assert seen["raw_path"] == esperado.encode()
    assert seen["root_path"] == root_path


async def test_websocket_tambem_e_prefixado() -> None:
    seen = await _run({"type": "websocket", "root_path": "/p", "path": "/ws", "raw_path": b"/ws"})
    assert seen["path"] == "/p/ws"
    assert seen["raw_path"] == b"/p/ws"


async def test_lifespan_passa_intocado() -> None:
    """O scope de lifespan não tem `path`; o middleware não pode nem tentar lê-lo."""
    assert await _run({"type": "lifespan"}) == {"type": "lifespan"}


async def test_sem_raw_path_so_path_e_alterado() -> None:
    seen = await _run({"type": "http", "root_path": "/p", "path": "/docs"})
    assert seen["path"] == "/p/docs"
    assert "raw_path" not in seen
