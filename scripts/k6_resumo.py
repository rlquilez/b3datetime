"""Tripwire e resumo do teste de carga (job "Performance · k6").

O k6 dá o veredito pelos limiares de ``tests/load/smoke.js``. Este script cobre o que ele
não vê:

* **cobertura** — toda operação do contrato (``tests/contract/openapi.json``) precisa ter
  uma entrada em ``ENDPOINTS`` no script do k6, e essa entrada precisa ter **amostras** no
  resultado. Um limiar de p95 sobre um endpoint que nunca foi chamado passa em silêncio
  (o p95 de nada é zero);
* **veredito independente** — qualquer limiar cruzado reprova aqui também, para que um
  ``--no-thresholds`` esquecido no workflow não desligue o gate;
* o **resumo** do run: latência por endpoint, vazão, falhas e o health sob carga.

No ``--summary-export`` do k6, ``"thresholds": {"p(95)<250": false}`` quer dizer que o
limiar **não** foi cruzado.

Uso: ``python scripts/k6_resumo.py k6.json tests/load/smoke.js tests/contract/openapi.json``
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ARGUMENTOS = 3  # resultado, script e contrato
METODOS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
# `nome: { caminho: '/v1/...'` no objeto ENDPOINTS de tests/load/smoke.js.
ENDPOINT_JS = re.compile(r"^\s*(\w+): \{ caminho: '([^']+)'", re.MULTILINE)
DURACAO = "http_req_duration{{endpoint:{}}}"
HEALTH_RELATIVO = "health_sob_carga_relativo"


def endpoints_do_script(texto: str) -> dict[str, str]:
    """``nome → caminho`` de cada entrada de ``ENDPOINTS`` no script do k6."""
    return dict(ENDPOINT_JS.findall(texto))


def caminhos_do_contrato(contrato: dict[str, Any]) -> set[str]:
    """Caminhos com alguma operação no contrato, sem o prefixo de ``servers``."""
    return {
        caminho
        for caminho, item in contrato["paths"].items()
        if any(metodo in METODOS for metodo in item)
    }


def limiares_cruzados(metricas: dict[str, Any]) -> list[str]:
    return sorted(
        f"{nome}: {limiar}"
        for nome, metrica in metricas.items()
        for limiar, cruzado in (metrica.get("thresholds") or {}).items()
        if cruzado
    )


def problemas(metricas: dict[str, Any], endpoints: dict[str, str], contrato: set[str]) -> list[str]:
    erros: list[str] = []
    if not endpoints:
        erros.append("nenhum endpoint encontrado no script do k6: o tripwire estaria vazio")
    erros += [
        f"{caminho} está no contrato e não tem cenário no k6"
        for caminho in sorted(contrato - set(endpoints.values()))
    ]
    erros += [
        f"{nome} ({caminho}) não recebeu nenhuma requisição"
        for nome, caminho in sorted(endpoints.items())
        if not (metricas.get(DURACAO.format(nome)) or {}).get("max")
    ]
    erros += [f"limiar cruzado — {c}" for c in limiares_cruzados(metricas)]
    return erros


def _ms(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:.1f} ms"


def resumo(metricas: dict[str, Any], endpoints: dict[str, str]) -> str:
    reqs = metricas.get("http_reqs") or {}
    # Métrica de taxa: `passes` conta os valores verdadeiros — aqui, as requisições que falharam.
    falhas = metricas.get("http_req_failed") or {}
    relativo = metricas.get(HEALTH_RELATIVO) or {}
    descartadas = (metricas.get("dropped_iterations") or {}).get("count", 0)
    linhas = [
        "## Performance · k6",
        "",
        (
            f"**{reqs.get('count', 0)} requisições** ({reqs.get('rate', 0):.1f}/s)"
            f" · falhas: {falhas.get('passes', 0)}"
            f" · iterações descartadas: {descartadas}"
            f" · health sob carga: p95 = {relativo.get('p(95)', 0):.2f} vezes o ocioso"
        ),
        "",
        "| Endpoint | Caminho | mediana | p95 | p99 | máx | Limiar |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    nomes = [*sorted(endpoints), *(["caro"] if DURACAO.format("caro") in metricas else [])]
    for nome in nomes:
        m = metricas.get(DURACAO.format(nome)) or {}
        caminho = endpoints.get(nome, "/v1/trading-days?…&exclude=true")
        situacao = ", ".join(
            f"{'❌' if cruzado else '✅'} {limiar}"
            for limiar, cruzado in (m.get("thresholds") or {}).items()
        )
        linhas.append(
            f"| {nome} | `{caminho}` | {_ms(m.get('med'))} | {_ms(m.get('p(95)'))}"
            f" | {_ms(m.get('p(99)'))} | {_ms(m.get('max'))} | {situacao or '—'} |"
        )
    return "\n".join(linhas) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != ARGUMENTOS:
        print("uso: k6_resumo.py k6.json smoke.js openapi.json", file=sys.stderr)
        return 2
    metricas: dict[str, Any] = json.loads(Path(argv[0]).read_text(encoding="utf-8"))["metrics"]
    endpoints = endpoints_do_script(Path(argv[1]).read_text(encoding="utf-8"))
    contrato = caminhos_do_contrato(json.loads(Path(argv[2]).read_text(encoding="utf-8")))

    texto = resumo(metricas, endpoints)
    print(texto)
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with Path(destino).open("a", encoding="utf-8") as f:
            f.write(texto)

    erros = problemas(metricas, endpoints, contrato)
    for erro in erros:
        print(f"::error::{erro}")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
