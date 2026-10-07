"""Gate do teste de mutação: score do mutmut contra o limiar do projeto.

Lê ``mutants/mutmut-cicd-stats.json`` (de ``mutmut export-cicd-stats``) e a lista de
sobreviventes (de ``mutmut results``), calcula o score e reprova abaixo do limiar
``[tool.b3datetime.quality] mutation_min_score`` do ``pyproject.toml``.

O score é ``detectados / avaliados``:

* **detectados**: mortos pela suíte (``killed``), mais os que travaram (``timeout``) ou
  derrubaram o processo (``segfault``) — em todos, a suíte percebeu a mudança;
* **avaliados**: os detectados, mais os sobreviventes, os sem teste nenhum (``no_tests``)
  e os suspeitos (``suspicious``). Os pulados (``skipped``) ficam de fora.

Reprova também com **zero** mutantes avaliados ou zero detectados: um run que não ativou
mutante nenhum produziria um score vazio — é o que aconteceria, por exemplo, com o pacote
chamado ``src`` (#52) ou com a cobertura ligada no pytest da mutação (todo mutante
"morreria" no ``fail_under``).

Uso: ``python scripts/mutation_gate.py mutants/mutmut-cicd-stats.json sobreviventes.txt``
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ARGUMENTOS = 2  # stats e sobreviventes


@dataclass(frozen=True)
class Resultado:
    detectados: int
    avaliados: int

    @property
    def score(self) -> float:
        return 100.0 * self.detectados / self.avaliados if self.avaliados else 0.0


def resultado(stats: dict[str, int]) -> Resultado:
    detectados = stats.get("killed", 0) + stats.get("timeout", 0) + stats.get("segfault", 0)
    nao_detectados = (
        stats.get("survived", 0) + stats.get("no_tests", 0) + stats.get("suspicious", 0)
    )
    return Resultado(detectados=detectados, avaliados=detectados + nao_detectados)


def limiar(pyproject: Path) -> float:
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return float(config["tool"]["b3datetime"]["quality"]["mutation_min_score"])


def sobreviventes(texto: str) -> list[str]:
    """Nomes dos mutantes a partir da saída de ``mutmut results`` (``nome: survived``)."""
    return [
        linha.split(":", 1)[0].strip()
        for linha in texto.splitlines()
        if linha.strip().endswith(("survived", "no tests", "suspicious"))
    ]


def problemas(res: Resultado, minimo: float) -> list[str]:
    if res.avaliados == 0:
        return ["nenhum mutante avaliado: o mutmut não ativou mutante algum"]
    if res.detectados == 0:
        return ["nenhum mutante detectado: a suíte não rodou contra o código mutado"]
    if res.score < minimo:
        return [f"score de mutação {res.score:.2f}% abaixo do limiar de {minimo:.2f}%"]
    return []


def resumo(res: Resultado, minimo: float, nomes: list[str], stats: dict[str, int]) -> str:
    linhas = [
        "## Teste de mutação (mutmut)",
        "",
        f"**Score: {res.score:.2f}%** ({res.detectados} de {res.avaliados}) · limiar {minimo:.2f}%",
        "",
        "| Mortos | Timeout | Sobreviventes | Sem teste | Suspeitos | Pulados |",
        "|---:|---:|---:|---:|---:|---:|",
        "| {killed} | {timeout} | {survived} | {no_tests} | {suspicious} | {skipped} |".format(
            **{
                k: stats.get(k, 0)
                for k in ("killed", "timeout", "survived", "no_tests", "suspicious", "skipped")
            }
        ),
    ]
    if nomes:
        linhas += ["", "<details><summary>Sobreviventes</summary>", "", "```"]
        linhas += nomes
        linhas += ["```", "", "</details>"]
    return "\n".join(linhas) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != ARGUMENTOS:
        print("uso: mutation_gate.py mutmut-cicd-stats.json sobreviventes.txt", file=sys.stderr)
        return 2
    stats: dict[str, int] = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    nomes = sobreviventes(Path(argv[1]).read_text(encoding="utf-8"))
    res = resultado(stats)
    minimo = limiar(RAIZ / "pyproject.toml")

    texto = resumo(res, minimo, nomes, stats)
    print(texto)
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with Path(destino).open("a", encoding="utf-8") as f:
            f.write(texto)

    erros = problemas(res, minimo)
    for erro in erros:
        print(f"::error::{erro}")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
