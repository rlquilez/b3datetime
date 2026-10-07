"""Gera o snapshot do contrato OpenAPI em ``tests/contract/openapi.json``.

O snapshot é o ``/openapi.json`` que a API serve atrás do Kong (``ROOT_PATH=/b3datetime``),
obtido em processo, com ``Settings(_env_file=None)`` — determinístico, sem depender de um
``.env`` local nem de rede. Versioná-lo faz toda mudança de contrato aparecer no diff do
commit, e é a base com que o job ``Contrato · oasdiff`` compara a versão nova.

Uso:
    PYTHONPATH=src python scripts/gerar_openapi.py           # (re)gera o arquivo
    PYTHONPATH=src python scripts/gerar_openapi.py --check   # só confere; sai 1 se divergir
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from b3datetime.config import Settings
from b3datetime.main import create_app

RAIZ = Path(__file__).resolve().parents[1]
SNAPSHOT = RAIZ / "tests" / "contract" / "openapi.json"
PREFIXO_PUBLICO = "/b3datetime"


async def contrato_servido() -> dict[str, Any]:
    """O ``/openapi.json`` como a produção serve: com o prefixo do Kong em ``servers``."""
    app = create_app(Settings(_env_file=None, root_path=PREFIXO_PUBLICO))
    transporte = httpx.ASGITransport(app=app, root_path=PREFIXO_PUBLICO)
    async with httpx.AsyncClient(transport=transporte, base_url="http://contrato") as cliente:
        resposta = await cliente.get("/openapi.json")
    resposta.raise_for_status()
    documento: dict[str, Any] = resposta.json()
    return documento


def serializar(documento: dict[str, Any]) -> str:
    """JSON estável e legível em diff: indentado, com acentos preservados e newline final."""
    return json.dumps(documento, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    atual = serializar(asyncio.run(contrato_servido()))
    if "--check" in argv:
        if SNAPSHOT.read_text(encoding="utf-8") != atual:
            print(
                f"{SNAPSHOT.relative_to(RAIZ)} está desatualizado: "
                "rode `PYTHONPATH=src python scripts/gerar_openapi.py` e revise o diff."
            )
            return 1
        print("snapshot do contrato em dia")
        return 0
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(atual, encoding="utf-8")
    print(f"snapshot gravado em {SNAPSHOT.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
