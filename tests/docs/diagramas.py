"""Os diagramas Mermaid do repositório: todo bloco ```` ```mermaid ```` de todo ``.md`` rastreado
e os modelos ``.mmd`` da skill ``mermaid-design``.

Fonte única para o bloco "Documentação · diagramas" (``tests/docs``): os testes estáticos,
o Agentic Mermaid e o render no Chromium iteram sobre :func:`diagramas`. Um ``.md`` novo
com diagrama entra na verificação sozinho — a cobertura de 100% não depende de lista.

O design system que os testes impõem está em ``.claude/skills/mermaid-design/SKILL.md``.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
# Os modelos da skill: diagramas prontos para copiar, verificados como os da documentação.
MODELOS = Path(".claude/skills/mermaid-design/modelos")
BLOCO = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
# Pastas que não são documentação publicada do projeto.
IGNORADOS = (".history/", "node_modules/")


@dataclass(frozen=True)
class Diagrama:
    """Um bloco Mermaid: onde está e o código-fonte, sem as cercas."""

    arquivo: str
    indice: int
    linha: int
    fonte: str

    @property
    def id(self) -> str:
        """Identificador estável para o pytest e para os arquivos de captura."""
        nome = Path(self.arquivo).stem if self.arquivo.endswith(".mmd") else self.arquivo
        return f"{nome.replace('/', '__').removesuffix('.md')}-{self.indice}"

    @property
    def corpo(self) -> str:
        """O diagrama sem o frontmatter de configuração."""
        return FRONTMATTER.sub("", self.fonte, count=1)

    @property
    def tipo(self) -> str:
        """A palavra-chave do tipo (``flowchart``, ``sequenceDiagram``…)."""
        for linha in self.corpo.splitlines():
            texto = linha.strip()
            if texto and not texto.startswith("%%"):
                return texto.split()[0]
        return ""


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def extrair(arquivo: str, texto: str) -> list[Diagrama]:
    """Os blocos Mermaid de um Markdown, na ordem em que aparecem."""
    return [
        Diagrama(arquivo, indice, texto.count("\n", 0, achado.start()) + 1, achado.group(1))
        for indice, achado in enumerate(BLOCO.finditer(texto))
    ]


def arquivos_markdown(raiz: Path = RAIZ) -> list[str]:
    """Os ``.md`` rastreados pelo git — o que o GitHub publica."""
    saida = subprocess.run(
        ["git", "ls-files", "*.md"],  # noqa: S607 — git do ambiente, argumentos fixos
        cwd=raiz,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(a for a in saida.splitlines() if not a.startswith(IGNORADOS))


def diagramas(raiz: Path = RAIZ) -> list[Diagrama]:
    """Todos os diagramas Mermaid do repositório: os blocos dos ``.md`` e os modelos."""
    blocos = [
        d
        for arquivo in arquivos_markdown(raiz)
        for d in extrair(arquivo, (raiz / arquivo).read_text(encoding="utf-8"))
    ]
    modelos = [
        Diagrama(str(MODELOS / m.name), 0, 1, m.read_text(encoding="utf-8"))
        for m in sorted((raiz / MODELOS).glob("*.mmd"))
    ]
    return blocos + modelos
