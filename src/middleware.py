"""Middleware que restaura o prefixo do proxy em ``scope["path"]``.

Contrato ASGI: ``path`` é o caminho completo e ``root_path`` é o prefixo em que a
aplicação está montada — logo ``path`` sempre começa com ``root_path``. O Starlette
(>= 0.35) depende disso: ``get_route_path()`` obtém o caminho roteável removendo
``root_path`` do início de ``path``, e só remove se ``path`` de fato começar com ele.

Atrás do Kong com ``strip_path: true`` (o padrão) o prefixo chega removido: ``path`` é
``/docs`` enquanto ``ROOT_PATH`` — necessário para que ``servers`` do OpenAPI e o
"Try it out" do Swagger apontem para ``/<prefixo>`` — faz o FastAPI gravar
``root_path="/<prefixo>"`` no scope. As rotas simples ainda casavam (a remoção era um
no-op), mas o ``Mount("/static")`` propagava ``root_path="/<prefixo>/static"`` para o
``StaticFiles``, que não conseguia removê-lo e procurava ``static/<arquivo>`` dentro do
diretório de assets: 404 em todos os assets, documentação em branco em produção. O
redirect de barra final sofria do mesmo mal e montava o ``Location`` sem o prefixo.

Este middleware recompõe ``path`` (e ``raw_path``) prefixando ``root_path`` quando ele
ainda não está lá. É exatamente o que o uvicorn faz com ``--root-path``; com
``strip_path: false`` ou ``--root-path`` o prefixo já vem em ``path`` e nada muda, então
as duas configurações do Kong funcionam.

Ressalva: ``ROOT_PATH`` não pode ser prefixo de uma rota da própria API (``/v1``,
``/docs``, ``/redoc``, ``/static``, ``/openapi.json``) — a heurística "já começa com o
prefixo" ficaria ambígua.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

# Só scopes que têm caminho. O scope de lifespan não tem ``path``.
_PREFIXABLE_TYPES = frozenset({"http", "websocket"})


class RootPathPrefixMiddleware:
    """Garante ``scope["path"].startswith(scope["root_path"])``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in _PREFIXABLE_TYPES:
            root_path: str = scope.get("root_path", "")
            path: str = scope["path"]
            if root_path and path != root_path and not path.startswith(root_path + "/"):
                scope["path"] = root_path + path
                raw_path: bytes | None = scope.get("raw_path")
                if raw_path is not None:
                    scope["raw_path"] = root_path.encode("utf-8") + raw_path
        await self.app(scope, receive, send)
