"""O Agentic Mermaid (``am``) aplicado aos diagramas do repositório, por canal local.

O ``am verify`` modela a estrutura (nós, arestas, grupos, rótulos) e devolve diagnósticos
em JSON; o ``am describe --format facts`` lê a semântica de volta. Três construções do
design system o cegariam, então o diagrama passa por :func:`para_agentic` antes:

* **rótulos em markdown string** (`` "`**Título**\\nsubtítulo`" ``): o ``am`` marca o
  fluxograma inteiro como opaco e o ``verify`` "passa" sem modelar nada. Viram rótulos
  simples com ``<br>`` — a mesma estrutura, sem o negrito;
* **``themeCSS``**: o modo seguro do ``am`` recusa CSS cru (``RENDER_FAILED``). O efeito
  dele no GitHub é medido pelo render no Chromium (:mod:`tests.docs.renderizador`);
* **o painel ``rect`` da sequência**: tudo dentro dele é um segmento opaco. Por convenção
  ele envolve todas as mensagens — abre depois dos participantes e fecha no último ``end``.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

PASTA = Path(__file__).resolve().parent
AM = PASTA / "node_modules" / ".bin" / "am"
# Linha de rótulo mais longa aceita (o mesmo limite do teste estático).
LIMITE_DE_ROTULO = 64

MARKDOWN = re.compile(r'"`(.*?)`"', re.DOTALL)
THEME_CSS = re.compile(r"(?m)^\s*themeCSS:.*\n")
PAINEL = re.compile(r"(?m)^\s*rect rgb\(.*\)\s*\n")

# Avisos que não dizem nada sobre o diagrama: campos que só o mermaid.js usa (curve,
# padding, mirrorActors…) e os blocos alt/loop, que o ``am`` não modela.
TOLERADOS = {("INEFFECTIVE_CONFIG", None), ("UNSUPPORTED_SYNTAX", "sequence_opaque_segment")}


def _rotulo_simples(achado: re.Match[str]) -> str:
    linhas = (linha.strip().replace("**", "") for linha in achado.group(1).split("\n"))
    return '"' + "<br>".join(linha for linha in linhas if linha) + '"'


def para_agentic(fonte: str) -> str:
    """O diagrama equivalente que o ``am`` consegue modelar (ver o docstring do módulo)."""
    fonte = THEME_CSS.sub("", fonte)
    fonte = MARKDOWN.sub(_rotulo_simples, fonte)
    if PAINEL.search(fonte):
        fonte = PAINEL.sub("", fonte, count=1)
        corpo = fonte.rstrip("\n").split("\n")
        if corpo[-1].strip() == "end":
            fonte = "\n".join(corpo[:-1]) + "\n"
    return fonte


def verificar(fonte: str) -> dict[str, Any]:
    """``am verify --json`` do diagrama já convertido; o JSON que o ``am`` devolve."""
    saida = subprocess.run(  # noqa: S603 — binário local fixado em tests/docs/package.json
        [str(AM), "verify", "-", "--json", "--label-cap", str(LIMITE_DE_ROTULO)],
        input=para_agentic(fonte),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    resultado: dict[str, Any] = json.loads(saida.stdout)
    return resultado


def avisos_relevantes(resultado: dict[str, Any]) -> list[dict[str, Any]]:
    """Os avisos que reprovam: tudo menos os de :data:`TOLERADOS`."""
    return [
        aviso
        for aviso in resultado["warnings"]
        if (aviso["code"], aviso.get("syntax")) not in TOLERADOS
    ]
