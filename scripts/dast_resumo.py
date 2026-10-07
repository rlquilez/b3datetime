"""Tripwire e resumo do DAST (job "DAST · OWASP ZAP").

O ZAP dá o veredito por risco (job ``exitStatus`` de ``tests/dast/plano-imagem.yaml``).
Este script cobre o que ele não enxerga:

* **cobertura** — toda operação do contrato (``tests/contract/openapi.json``) precisa
  aparecer na árvore de sites que o ZAP exporta, **com resposta 2xx**. Uma varredura que
  não alcançou um endpoint passaria verde sem tê-lo atacado; uma que só alcançou a
  validação também: antes dos exemplos de parâmetro, o ZAP mandava ``start=start`` para
  ``/v1/trading-days``, recebia 422 e nunca chegava à lógica do endpoint;
* **veredito independente** — alerta Low ou acima que não seja falso positivo reprova
  aqui também, para que um ``exitStatus`` removido do plano não desligue o gate;
* o **resumo** do run, com os alertas por risco e as operações alcançadas.

Uso: ``python scripts/dast_resumo.py zap.json arvore.yaml tests/contract/openapi.json [título]``
— o título distingue o resumo do plano passivo de produção (``tests/dast/plano-producao.yaml``).
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

ARGUMENTOS = (3, 4)  # relatório, árvore, contrato e, opcional, o título do resumo
TITULO = "DAST · OWASP ZAP"
METODOS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
# No traditional-json do ZAP, confiança "0" é falso positivo (alertFilter com
# `newRisk: False Positive`): o alerta continua no relatório, mas não conta.
FALSO_POSITIVO = "0"
RISCOS = {"3": "Alto", "2": "Médio", "1": "Baixo", "0": "Informativo"}


@dataclass(frozen=True, order=True)
class Operacao:
    metodo: str
    caminho: str


@dataclass(frozen=True)
class No:
    metodo: str
    caminho: str
    status: int


@dataclass(frozen=True)
class Alerta:
    regra: str
    nome: str
    risco: str
    confianca: str
    ocorrencias: int

    @property
    def falso_positivo(self) -> bool:
        return self.confianca == FALSO_POSITIVO

    @property
    def reprova(self) -> bool:
        return int(self.risco) >= 1 and not self.falso_positivo


def operacoes(contrato: dict[str, Any]) -> list[Operacao]:
    """As operações do contrato, com o prefixo de ``servers`` (o ``ROOT_PATH``)."""
    servidores = contrato.get("servers") or [{"url": ""}]
    prefixo = str(servidores[0]["url"]).rstrip("/")
    return sorted(
        Operacao(metodo.upper(), prefixo + caminho)
        for caminho, item in contrato["paths"].items()
        for metodo in item
        if metodo in METODOS
    )


def nos(arvore: Any) -> list[No]:
    """Os nós da árvore de sites com resposta — os nós só estruturais não têm status."""
    encontrados: list[No] = []
    pendentes = list(arvore or [])
    while pendentes:
        no = pendentes.pop()
        pendentes.extend(no.get("children") or [])
        if "statusCode" in no and "url" in no:
            encontrados.append(No(no["method"], urlsplit(no["url"]).path, int(no["statusCode"])))
    return encontrados


def _padrao(caminho: str) -> re.Pattern[str]:
    """Caminho do contrato como regex: ``{parametro}`` casa um segmento."""
    partes = re.split(r"\{[^}/]+\}", caminho)
    return re.compile("[^/]+".join(re.escape(p) for p in partes) + r"\Z")


def nao_alcancadas(ops: list[Operacao], arvore: list[No]) -> list[Operacao]:
    """Operações sem nenhum nó 2xx correspondente na árvore."""
    faltando = []
    for op in ops:
        padrao = _padrao(op.caminho)
        if not any(
            n.metodo == op.metodo
            and padrao.match(n.caminho)
            and HTTPStatus.OK <= n.status < HTTPStatus.MULTIPLE_CHOICES
            for n in arvore
        ):
            faltando.append(op)
    return faltando


def alertas(relatorio: dict[str, Any]) -> list[Alerta]:
    return [
        Alerta(
            regra=str(a["pluginid"]),
            nome=a["name"],
            risco=str(a["riskcode"]),
            confianca=str(a["confidence"]),
            ocorrencias=int(a["count"]),
        )
        for site in relatorio.get("site", [])
        for a in site.get("alerts", [])
    ]


def problemas(ops: list[Operacao], arvore: list[No], lista: list[Alerta]) -> list[str]:
    erros: list[str] = []
    if not ops:
        erros.append("o contrato não tem operações: o tripwire estaria vazio")
    if not arvore:
        erros.append("a árvore de sites está vazia: o ZAP não alcançou a aplicação")
    erros += [
        f"{op.metodo} {op.caminho} não foi alcançada com resposta 2xx pela varredura"
        for op in nao_alcancadas(ops, arvore)
    ]
    erros += [
        f"alerta {RISCOS.get(a.risco, a.risco)} não filtrado: {a.regra} {a.nome}"
        for a in lista
        if a.reprova
    ]
    return erros


def resumo(ops: list[Operacao], arvore: list[No], lista: list[Alerta], titulo: str = TITULO) -> str:
    faltando = set(nao_alcancadas(ops, arvore))
    linhas = [
        f"## {titulo}",
        "",
        (
            f"**{len(ops) - len(faltando)} de {len(ops)} operações do contrato alcançadas"
            f" com 2xx** · {len(arvore)} nós com resposta na árvore de sites"
        ),
        "",
        "| Risco | Regra | Alerta | Ocorrências |",
        "|---|---|---|---:|",
    ]
    ordenados = sorted(lista, key=lambda a: (a.falso_positivo, -int(a.risco), a.regra))
    for a in ordenados:
        risco = "Falso positivo (filtrado)" if a.falso_positivo else RISCOS.get(a.risco, a.risco)
        linhas.append(f"| {risco} | {a.regra} | {a.nome} | {a.ocorrencias} |")
    if not lista:
        linhas.append("| — | — | nenhum alerta | 0 |")
    linhas += ["", "<details><summary>Operações</summary>", ""]
    linhas += [f"- {'❌' if op in faltando else '✅'} `{op.metodo} {op.caminho}`" for op in ops]
    linhas += ["", "</details>"]
    return "\n".join(linhas) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) not in ARGUMENTOS:
        print("uso: dast_resumo.py zap.json arvore.yaml openapi.json [título]", file=sys.stderr)
        return 2
    relatorio = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    arvore = nos(yaml.safe_load(Path(argv[1]).read_text(encoding="utf-8")))
    ops = operacoes(json.loads(Path(argv[2]).read_text(encoding="utf-8")))
    lista = alertas(relatorio)

    texto = resumo(ops, arvore, lista, *argv[3:])
    print(texto)
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with Path(destino).open("a", encoding="utf-8") as f:
            f.write(texto)

    erros = problemas(ops, arvore, lista)
    for erro in erros:
        print(f"::error::{erro}")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
