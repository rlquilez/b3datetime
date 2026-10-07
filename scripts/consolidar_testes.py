"""Consolida os relatórios dos blocos de teste e aplica os tripwires do pipeline.

Roda no job "Cobertura · combinada", depois de cada bloco (unitários, componente,
integração, property-based…) ter publicado o seu ``junit-<bloco>.xml``. Reprova quando:

* algum teste foi **pulado** — no CI todo recurso existe (Redis como service, calendário
  real), então um skip é um teste que deixou de rodar sem ninguém perceber;
* o ``coverage.xml`` combinado não tem caminhos ``src/`` — sem eles o SonarQube não casa
  os arquivos com ``sonar.sources`` e reporta 0% de cobertura em silêncio;
* nenhum relatório de bloco foi encontrado, ou algum bloco não executou teste nenhum.

Também escreve no resumo do run uma tabela com a contagem de cada bloco.

Uso: ``python scripts/consolidar_testes.py coverage.xml junit-*.xml``
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

PREFIXO_JUNIT = "junit-"


@dataclass(frozen=True)
class Bloco:
    """Totais de um ``junit-<bloco>.xml``."""

    nome: str
    testes: int
    falhas: int
    erros: int
    pulados: int
    segundos: float


def ler_junit(caminho: Path) -> Bloco:
    raiz = ET.parse(caminho).getroot()  # noqa: S314 - relatório gerado pelo próprio pytest
    suites = [raiz] if raiz.tag == "testsuite" else list(raiz.iter("testsuite"))
    nome = caminho.stem.removeprefix(PREFIXO_JUNIT)
    return Bloco(
        nome=nome,
        testes=sum(int(s.get("tests", 0)) for s in suites),
        falhas=sum(int(s.get("failures", 0)) for s in suites),
        erros=sum(int(s.get("errors", 0)) for s in suites),
        pulados=sum(int(s.get("skipped", 0)) for s in suites),
        segundos=sum(float(s.get("time", 0)) for s in suites),
    )


def problemas(blocos: list[Bloco], coverage_xml: str) -> list[str]:
    """Lista de violações; vazia quando tudo está em ordem."""
    erros: list[str] = []
    if not blocos:
        erros.append("nenhum relatório junit-<bloco>.xml encontrado")
    for b in blocos:
        if b.testes == 0:
            erros.append(f"o bloco '{b.nome}' não executou nenhum teste")
        if b.pulados:
            erros.append(
                f"o bloco '{b.nome}' pulou {b.pulados} teste(s); no CI nada pode ser pulado"
            )
        if b.falhas or b.erros:
            erros.append(f"o bloco '{b.nome}' tem {b.falhas} falha(s) e {b.erros} erro(s)")
    if 'filename="src/' not in coverage_xml:
        erros.append("coverage.xml sem caminhos 'src/...'; o SonarQube reportaria 0%")
    return erros


def tabela(blocos: list[Bloco]) -> str:
    linhas = [
        "## Testes por bloco",
        "",
        "| Bloco | Testes | Falhas | Erros | Pulados | Tempo (s) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    linhas.extend(
        f"| {b.nome} | {b.testes} | {b.falhas} | {b.erros} | {b.pulados} | {b.segundos:.1f} |"
        for b in blocos
    )
    total = sum(b.testes for b in blocos)
    linhas.append(f"| **total** | **{total}** | | | | |")
    return "\n".join(linhas) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 1:
        print("uso: consolidar_testes.py coverage.xml junit-<bloco>.xml...", file=sys.stderr)
        return 2
    coverage_xml = Path(argv[0]).read_text(encoding="utf-8")
    blocos = sorted((ler_junit(Path(p)) for p in argv[1:]), key=lambda b: b.nome)

    resumo = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo:
        with Path(resumo).open("a", encoding="utf-8") as f:
            f.write(tabela(blocos))
    print(tabela(blocos))

    erros = problemas(blocos, coverage_xml)
    for erro in erros:
        print(f"::error::{erro}")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
