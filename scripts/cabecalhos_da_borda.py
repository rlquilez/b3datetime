"""Headers de segurança da borda, conferidos na produção (job "Produção · pós-deploy").

Os headers de segurança das respostas são responsabilidade da borda (Cloudflare), não da
aplicação — um dono só evita valores duplicados ou divergentes. Por isso o DAST da imagem
os rebaixa a informativo, e quem os confere é este script, na resposta que o cliente
recebe de fato. Confere o **valor**, não só a presença: um HSTS com ``max-age=0`` está
presente e desliga a proteção.

O modo vem de ``[tool.b3datetime.quality] edge_headers_required`` no ``pyproject.toml``:
com ``false``, o que falta vira aviso (``::warning::``) e o job passa; com ``true``,
reprova. Passa a ``true`` quando a borda estiver configurada — a partir daí, uma regra
desfeita no Cloudflare quebra o pipeline em vez de passar despercebida.

Uso: ``python scripts/cabecalhos_da_borda.py https://api.quilez.cloud/b3datetime``
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError

RAIZ = Path(__file__).resolve().parents[1]
ARGUMENTOS = 1  # URL base pública
# 180 dias: o mínimo usual para HSTS (e o exigido para a lista de preload é 1 ano).
HSTS_MINIMO_SEGUNDOS = 15_552_000
REFERRER_ACEITOS = frozenset(
    {"no-referrer", "same-origin", "strict-origin", "strict-origin-when-cross-origin"}
)
# Páginas: as duas formas de resposta — JSON da API e HTML da documentação.
PAGINAS_API = ("/", "/v1/health")
PAGINAS_DOCS = ("/docs", "/redoc")
TEMPO_LIMITE_SEGUNDOS = 15

Buscador = Callable[[str], Mapping[str, str]]


@dataclass(frozen=True)
class Verificacao:
    pagina: str
    cabecalho: str
    valor: str | None
    ok: bool
    motivo: str


def _max_age(hsts: str) -> int | None:
    achado = re.search(r"max-age\s*=\s*\"?(\d+)", hsts, re.IGNORECASE)
    return int(achado.group(1)) if achado else None


def _diretivas_csp(csp: str) -> dict[str, str]:
    diretivas: dict[str, str] = {}
    for parte in csp.split(";"):
        nome, _, valor = parte.strip().partition(" ")
        if nome:
            diretivas[nome.lower()] = valor.strip()
    return diretivas


def avaliar(pagina: str, cabecalhos: Mapping[str, str]) -> list[Verificacao]:
    """Confere os headers de uma resposta. ``cabecalhos`` com nomes em minúsculas."""
    hsts = cabecalhos.get("strict-transport-security")
    idade = _max_age(hsts) if hsts is not None else None
    csp = cabecalhos.get("content-security-policy")
    diretivas = _diretivas_csp(csp) if csp is not None else {}
    xfo = cabecalhos.get("x-frame-options")
    nosniff = cabecalhos.get("x-content-type-options")
    referrer = cabecalhos.get("referrer-policy")
    eh_api = pagina in PAGINAS_API

    verificacoes = [
        Verificacao(
            pagina,
            "Strict-Transport-Security",
            hsts,
            idade is not None and idade >= HSTS_MINIMO_SEGUNDOS,
            f"max-age ≥ {HSTS_MINIMO_SEGUNDOS} (180 dias); max-age=0 desliga o HSTS",
        ),
        Verificacao(
            pagina,
            "X-Content-Type-Options",
            nosniff,
            (nosniff or "").strip().lower() == "nosniff",
            "nosniff",
        ),
        Verificacao(pagina, "X-Frame-Options", xfo, (xfo or "").strip().upper() == "DENY", "DENY"),
        Verificacao(
            pagina,
            "Referrer-Policy",
            referrer,
            (referrer or "").strip().lower() in REFERRER_ACEITOS,
            "no-referrer (ou same-origin, strict-origin, strict-origin-when-cross-origin)",
        ),
        Verificacao(
            pagina,
            "Content-Security-Policy",
            csp,
            diretivas.get("frame-ancestors") == "'none'"
            and (not eh_api or diretivas.get("default-src") == "'none'"),
            "frame-ancestors 'none'" + (" e default-src 'none'" if eh_api else ""),
        ),
    ]
    if "cf-mitigated" in cabecalhos:
        verificacoes.append(
            Verificacao(
                pagina,
                "cf-mitigated",
                cabecalhos["cf-mitigated"],
                False,
                "o Cloudflare desafiou o runner: crie uma regra de skip no WAF para o CI",
            )
        )
    return verificacoes


def buscar(url: str) -> Mapping[str, str]:
    """Headers da resposta (inclusive de erro HTTP), com nomes em minúsculas."""
    pedido = urllib.request.Request(  # noqa: S310 — URL https fixa, vinda do workflow
        url, headers={"User-Agent": "b3datetime-ci/pos-deploy"}
    )
    try:
        with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE_SEGUNDOS) as resposta:  # noqa: S310
            itens = resposta.headers.items()
    except HTTPError as erro:
        # A resposta de erro também passou pela borda; o corpo não interessa.
        with erro:
            itens = erro.headers.items()
    return {nome.lower(): valor for nome, valor in itens}


def exigido(pyproject: Path) -> bool:
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return bool(config["tool"]["b3datetime"]["quality"]["edge_headers_required"])


def verificar(base: str, busca: Buscador) -> list[Verificacao]:
    base = base.rstrip("/")
    return [
        v for pagina in (*PAGINAS_API, *PAGINAS_DOCS) for v in avaliar(pagina, busca(base + pagina))
    ]


def resumo(verificacoes: list[Verificacao], obrigatorio: bool) -> str:
    modo = "obrigatórios (reprova)" if obrigatorio else "em observação (só avisa)"
    linhas = [
        "## Headers de segurança da borda",
        "",
        f"Modo: **{modo}** — `[tool.b3datetime.quality] edge_headers_required`",
        "",
        "| Página | Header | Valor atual | Esperado |",
        "|---|---|---|---|",
    ]
    for v in verificacoes:
        valor = f"`{v.valor}`" if v.valor is not None else "*ausente*"
        linhas.append(
            f"| `{v.pagina}` | {v.cabecalho} | {'✅' if v.ok else '❌'} {valor} | {v.motivo} |"
        )
    return "\n".join(linhas) + "\n"


def main(argv: list[str], busca: Buscador = buscar) -> int:
    if len(argv) != ARGUMENTOS:
        print("uso: cabecalhos_da_borda.py https://host/prefixo", file=sys.stderr)
        return 2
    obrigatorio = exigido(RAIZ / "pyproject.toml")
    verificacoes = verificar(argv[0], busca)

    texto = resumo(verificacoes, obrigatorio)
    print(texto)
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with Path(destino).open("a", encoding="utf-8") as f:
            f.write(texto)

    falhas = [v for v in verificacoes if not v.ok]
    nivel = "error" if obrigatorio else "warning"
    for v in falhas:
        print(f"::{nivel}::{v.pagina}: {v.cabecalho} — esperado {v.motivo}")
    return 1 if falhas and obrigatorio else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
