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
from collections.abc import Callable, Mapping, Sequence
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
# Fontes que deixam executar código que não veio de um arquivo do próprio host. Nenhuma
# página precisa delas: a documentação não tem script inline e o ReDoc roda sem a busca,
# que criava um worker a partir de blob: (#75).
FONTES_INSEGURAS = frozenset(
    {"'unsafe-inline'", "'unsafe-eval'", "*", "http:", "https:", "data:", "blob:"}
)
BASE_URI_RESTRITO = frozenset({"'none'", "'self'"})

# O que a busca devolve: os headers como pares, na ordem e com as repetições da resposta.
Itens = Sequence[tuple[str, str]]
Buscador = Callable[[str], Itens | Mapping[str, str]]
# Headers de segurança que a borda envia. Repetido, um deles indica uma regra do Cloudflare
# com Add em vez de Set ou duas regras sobrepostas — e o navegador aplica TODOS os CSP.
SEGURANCA = (
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "referrer-policy",
    "x-content-type-options",
)


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


def _efetiva(diretivas: Mapping[str, str], *cadeia: str) -> set[str]:
    """Fontes da primeira diretiva presente na cadeia de fallback da CSP (por exemplo,
    ``worker-src`` → ``script-src`` → ``default-src``). Sem nenhuma, nada é restrito."""
    for nome in cadeia:
        if nome in diretivas:
            return {fonte.lower() for fonte in diretivas[nome].split()}
    return {"*"}


def _csp_ok(pagina: str, diretivas: Mapping[str, str]) -> bool:
    """A política que vale para toda página: nada de enquadramento, nenhum script ou
    worker de fora de um arquivo do próprio host, nenhum plugin, ``<base>`` restrito; na
    API JSON, além disso, ``default-src 'none'``. Estilo inline é aceito nas páginas de
    documentação: o ReDoc injeta estilos em tempo de execução."""
    scripts = _efetiva(diretivas, "script-src", "default-src") | _efetiva(
        diretivas, "worker-src", "script-src", "default-src"
    )
    return (
        diretivas.get("frame-ancestors") == "'none'"
        and not scripts & FONTES_INSEGURAS
        and _efetiva(diretivas, "object-src", "default-src") == {"'none'"}
        and diretivas.get("base-uri") in BASE_URI_RESTRITO
        and (pagina not in PAGINAS_API or diretivas.get("default-src") == "'none'")
    )


def avaliar(pagina: str, cabecalhos: Mapping[str, str]) -> list[Verificacao]:
    """Confere os headers de uma resposta. ``cabecalhos`` com nomes em minúsculas."""
    hsts = cabecalhos.get("strict-transport-security")
    idade = _max_age(hsts) if hsts is not None else None
    csp = cabecalhos.get("content-security-policy")
    diretivas = _diretivas_csp(csp) if csp is not None else {}
    xfo = cabecalhos.get("x-frame-options")
    nosniff = cabecalhos.get("x-content-type-options")
    referrer = cabecalhos.get("referrer-policy")
    esperado_csp = (
        "frame-ancestors 'none'; script-src e worker-src sem 'unsafe-inline', 'unsafe-eval', "
        "blob:, data: nem curingas; object-src 'none'; base-uri 'none' ou 'self'"
    )
    if pagina in PAGINAS_API:
        esperado_csp = "default-src 'none'; " + esperado_csp

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
            pagina, "Content-Security-Policy", csp, _csp_ok(pagina, diretivas), esperado_csp
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


def buscar(url: str) -> Itens:
    """Headers da resposta (inclusive de erro HTTP), com nomes em minúsculas e as
    repetições preservadas — um dicionário esconderia um segundo CSP."""
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
    return [(nome.lower(), valor) for nome, valor in itens]


def repetidos(pagina: str, itens: Itens) -> list[Verificacao]:
    """Uma verificação reprovada por header de segurança que aparece mais de uma vez."""
    return [
        Verificacao(
            pagina,
            f"{nome} (repetido)",
            " ‖ ".join(valores),
            False,
            "um só header: repetido indica regra do Cloudflare com Add em vez de Set, ou "
            "duas regras sobrepostas — o navegador aplica todos os CSP",
        )
        for nome in SEGURANCA
        if len(valores := [v for n, v in itens if n == nome]) > 1
    ]


def exigido(pyproject: Path) -> bool:
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return bool(config["tool"]["b3datetime"]["quality"]["edge_headers_required"])


def verificar(base: str, busca: Buscador) -> list[Verificacao]:
    base = base.rstrip("/")
    verificacoes: list[Verificacao] = []
    for pagina in (*PAGINAS_API, *PAGINAS_DOCS):
        resposta = busca(base + pagina)
        itens = list(resposta.items()) if isinstance(resposta, Mapping) else list(resposta)
        verificacoes += avaliar(pagina, dict(itens)) + repetidos(pagina, itens)
    return verificacoes


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
