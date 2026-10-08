"""A verificação dos headers da borda (``scripts/cabecalhos_da_borda.py``).

O caso que motivou conferir **valor**, e não só presença: a produção responde
``Strict-Transport-Security: max-age=0; includeSubDomains; preload`` — o header existe e
o HSTS está desligado.
"""

from __future__ import annotations

import email.message
import io
import urllib.request
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError

import pytest

from scripts import cabecalhos_da_borda as borda
from scripts.cabecalhos_da_borda import (
    FONTES_INSEGURAS,
    HSTS_MINIMO_SEGUNDOS,
    avaliar,
    buscar,
    exigido,
    main,
    resumo,
    verificar,
)

# As regras da borda recomendadas no README (seção Segurança).
CSP_API = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
CSP_DOCS = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'none'; upgrade-insecure-requests"
)
# A regra que a borda aplicava à documentação enquanto as páginas tinham script inline.
CSP_DOCS_ANTIGA = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
    "worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
# A primeira CSP global configurada na borda (2026-10-07): estrita, mas sem default-src
# 'none' — boa para a documentação, não para a API JSON.
CSP_GLOBAL_DO_USUARIO = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
    "form-action 'self'; upgrade-insecure-requests;"
)


def _bons(csp: str = CSP_API) -> dict[str, str]:
    return {
        "strict-transport-security": f"max-age={HSTS_MINIMO_SEGUNDOS}; includeSubDomains",
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
        "content-security-policy": csp,
    }


def _reprovados(pagina: str, cabecalhos: Mapping[str, str]) -> list[str]:
    return [v.cabecalho for v in avaliar(pagina, cabecalhos) if not v.ok]


def test_borda_configurada_aprova_api_e_docs() -> None:
    assert _reprovados("/", _bons()) == []
    assert _reprovados("/docs", _bons(CSP_DOCS)) == []


def test_producao_de_hoje() -> None:
    """Medido em produção: só o nosniff está lá; o HSTS existe e está desligado."""
    hoje = {
        "strict-transport-security": "max-age=0; includeSubDomains; preload",
        "x-content-type-options": "nosniff",
    }
    assert _reprovados("/", hoje) == [
        "Strict-Transport-Security",
        "X-Frame-Options",
        "Referrer-Policy",
        "Content-Security-Policy",
    ]


@pytest.mark.parametrize(
    ("hsts", "ok"),
    [
        (f"max-age={HSTS_MINIMO_SEGUNDOS}", True),
        (f'max-age="{HSTS_MINIMO_SEGUNDOS}"; preload', True),
        (f"MAX-AGE = {HSTS_MINIMO_SEGUNDOS + 1}", True),
        (f"max-age={HSTS_MINIMO_SEGUNDOS - 1}", False),
        ("max-age=0; includeSubDomains; preload", False),
        ("includeSubDomains", False),
    ],
)
def test_hsts_exige_idade_minima(hsts: str, ok: bool) -> None:
    cabecalhos = {**_bons(), "strict-transport-security": hsts}
    assert ("Strict-Transport-Security" not in _reprovados("/", cabecalhos)) is ok


def test_hsts_ausente() -> None:
    cabecalhos = _bons()
    del cabecalhos["strict-transport-security"]
    assert _reprovados("/", cabecalhos) == ["Strict-Transport-Security"]


def test_csp_da_api_exige_default_src_none() -> None:
    """A CSP global do usuário (default-src 'self') protege a documentação, mas a API
    JSON não carrega nada: ali vale default-src 'none'."""
    assert _reprovados("/", _bons(CSP_GLOBAL_DO_USUARIO)) == ["Content-Security-Policy"]
    assert _reprovados("/v1/health", _bons(CSP_GLOBAL_DO_USUARIO)) == ["Content-Security-Policy"]
    # A da API é mais estrita que a da documentação: serve para as duas.
    assert _reprovados("/redoc", _bons(CSP_API)) == []


def test_a_csp_global_do_usuario_serve_para_a_documentacao() -> None:
    assert _reprovados("/docs", _bons(CSP_GLOBAL_DO_USUARIO)) == []


def test_a_regra_antiga_da_documentacao_reprova() -> None:
    """'unsafe-inline' em scripts e worker blob: só existiam pelo script inline e pela
    busca do ReDoc, que saíram em #75."""
    assert _reprovados("/docs", _bons(CSP_DOCS_ANTIGA)) == ["Content-Security-Policy"]
    assert _reprovados("/redoc", _bons(CSP_DOCS_ANTIGA)) == ["Content-Security-Policy"]


@pytest.mark.parametrize("fonte", sorted(FONTES_INSEGURAS))
def test_fonte_insegura_em_script_reprova(fonte: str) -> None:
    csp = CSP_DOCS.replace("script-src 'self'", f"script-src 'self' {fonte}")
    assert _reprovados("/docs", _bons(csp)) == ["Content-Security-Policy"]


@pytest.mark.parametrize(
    ("trecho", "pagina"),
    [
        # worker-src cai para script-src, que cai para default-src
        ("worker-src blob:", "/redoc"),
        ("worker-src 'self' 'unsafe-eval'", "/docs"),
    ],
)
def test_worker_inseguro_reprova(trecho: str, pagina: str) -> None:
    assert _reprovados(pagina, _bons(f"{CSP_DOCS}; {trecho}")) == ["Content-Security-Policy"]


def test_script_sem_diretiva_cai_no_default_src() -> None:
    csp = "default-src 'self' 'unsafe-inline'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
    assert _reprovados("/docs", _bons(csp)) == ["Content-Security-Policy"]
    assert _reprovados("/docs", _bons(csp.replace(" 'unsafe-inline'", ""))) == []


def test_sem_nenhuma_restricao_de_script_reprova() -> None:
    assert _reprovados("/redoc", _bons("frame-ancestors 'none'; base-uri 'none'")) == [
        "Content-Security-Policy"
    ]


@pytest.mark.parametrize(
    "csp",
    [
        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'",  # object-src vira 'self'
        "default-src 'none'; object-src 'self'; frame-ancestors 'none'; base-uri 'none'",
    ],
)
def test_object_src_efetivo_precisa_ser_none(csp: str) -> None:
    assert _reprovados("/docs", _bons(csp)) == ["Content-Security-Policy"]


@pytest.mark.parametrize("base", ["", "; base-uri https://outro.example"])
def test_base_uri_precisa_ser_restrito(base: str) -> None:
    csp = "default-src 'none'; frame-ancestors 'none'" + base
    assert _reprovados("/docs", _bons(csp)) == ["Content-Security-Policy"]


def test_estilo_inline_e_aceito_na_documentacao() -> None:
    """O ReDoc injeta estilos em tempo de execução: é o único 'unsafe-inline' aceito."""
    assert "style-src 'self' 'unsafe-inline'" in CSP_DOCS
    assert _reprovados("/redoc", _bons(CSP_DOCS)) == []


def test_csp_sem_frame_ancestors_reprova() -> None:
    assert _reprovados("/docs", _bons("default-src 'none'; base-uri 'none'")) == [
        "Content-Security-Policy"
    ]


@pytest.mark.parametrize(("valor", "ok"), [("deny", True), (" DENY ", True), ("SAMEORIGIN", False)])
def test_x_frame_options(valor: str, ok: bool) -> None:
    cabecalhos = {**_bons(), "x-frame-options": valor}
    assert ("X-Frame-Options" not in _reprovados("/", cabecalhos)) is ok


@pytest.mark.parametrize(
    ("valor", "ok"),
    [
        ("no-referrer", True),
        ("Strict-Origin-When-Cross-Origin", True),
        ("unsafe-url", False),
        ("no-referrer-when-downgrade", False),
    ],
)
def test_referrer_policy(valor: str, ok: bool) -> None:
    cabecalhos = {**_bons(), "referrer-policy": valor}
    assert ("Referrer-Policy" not in _reprovados("/", cabecalhos)) is ok


def test_nosniff_com_outro_valor_reprova() -> None:
    cabecalhos = {**_bons(), "x-content-type-options": "sniff"}
    assert _reprovados("/", cabecalhos) == ["X-Content-Type-Options"]


def test_desafio_do_cloudflare_reprova_com_instrucao() -> None:
    falhas = [v for v in avaliar("/", {**_bons(), "cf-mitigated": "challenge"}) if not v.ok]
    assert [v.cabecalho for v in falhas] == ["cf-mitigated"]
    assert "regra de skip no WAF" in falhas[0].motivo


def test_verificar_confere_as_quatro_paginas() -> None:
    pedidas: list[str] = []

    def busca(url: str) -> Mapping[str, str]:
        pedidas.append(url)
        return _bons(CSP_DOCS if url.endswith(("/docs", "/redoc")) else CSP_API)

    verificacoes = verificar("https://h/b3datetime/", busca)
    assert pedidas == [
        "https://h/b3datetime/",
        "https://h/b3datetime/v1/health",
        "https://h/b3datetime/docs",
        "https://h/b3datetime/redoc",
    ]
    assert len(verificacoes) == 20
    assert all(v.ok for v in verificacoes)


class _Resposta:
    def __init__(self, cabecalhos: email.message.Message) -> None:
        self.headers = cabecalhos


def _mensagem(**cabecalhos: str) -> email.message.Message:
    mensagem = email.message.Message()
    for nome, valor in cabecalhos.items():
        mensagem[nome.replace("_", "-")] = valor
    return mensagem


def test_buscar_normaliza_os_nomes(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def urlopen(_pedido: object, timeout: float) -> Iterator[_Resposta]:
        assert timeout == borda.TEMPO_LIMITE_SEGUNDOS
        yield _Resposta(_mensagem(X_Frame_Options="DENY"))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert buscar("https://h/") == [("x-frame-options", "DENY")]


def test_buscar_le_os_headers_de_uma_resposta_de_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um 503 do health também passa pela borda: os headers dele contam."""
    cabecalhos = _mensagem(Referrer_Policy="no-referrer")

    def urlopen(_pedido: object, **_opcoes: object) -> None:
        raise HTTPError("https://h/", 503, "indisponível", cabecalhos, io.BytesIO())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert buscar("https://h/") == [("referrer-policy", "no-referrer")]


def test_exigido_vem_do_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.b3datetime.quality]\nedge_headers_required = true\n")
    assert exigido(pyproject) is True
    assert exigido(borda.RAIZ / "pyproject.toml") in {True, False}


def test_resumo_mostra_modo_e_valores() -> None:
    verificacoes = avaliar("/", {"x-content-type-options": "nosniff"})
    texto = resumo(verificacoes, obrigatorio=False)
    assert "Modo: **em observação (só avisa)**" in texto
    assert "| `/` | X-Content-Type-Options | ✅ `nosniff` | nosniff |" in texto
    assert "| `/` | X-Frame-Options | ❌ *ausente* | DENY |" in texto
    assert "obrigatórios (reprova)" in resumo(verificacoes, obrigatorio=True)


@pytest.mark.parametrize(
    ("obrigatorio", "saida", "nivel"), [(False, 0, "warning"), (True, 1, "error")]
)
def test_main_avisa_ou_reprova_conforme_o_modo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    obrigatorio: bool,
    saida: int,
    nivel: str,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.b3datetime.quality]\nedge_headers_required = {str(obrigatorio).lower()}\n"
    )
    monkeypatch.setattr(borda, "RAIZ", tmp_path)
    sumario = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(sumario))

    assert main(["https://h/b3datetime"], busca=lambda _url: {}) == saida
    assert f"::{nivel}::/: X-Frame-Options — esperado DENY" in capsys.readouterr().out
    assert "## Headers de segurança da borda" in sumario.read_text(encoding="utf-8")


def test_main_aprova_com_a_borda_configurada(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.b3datetime.quality]\nedge_headers_required = true\n"
    )
    monkeypatch.setattr(borda, "RAIZ", tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def busca(url: str) -> Mapping[str, str]:
        return _bons(CSP_DOCS if url.endswith(("/docs", "/redoc")) else CSP_API)

    assert main(["https://h/b3datetime"], busca=busca) == 0


def test_main_com_argumentos_errados() -> None:
    assert main([]) == 2


def test_buscar_preserva_headers_repetidos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um dicionário guardaria só o último CSP e esconderia o outro."""
    mensagem = _mensagem(X_Frame_Options="DENY")
    mensagem["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline'"
    mensagem["Content-Security-Policy"] = "default-src 'none'"

    @contextmanager
    def urlopen(_pedido: object, timeout: float) -> Iterator[_Resposta]:
        assert timeout == borda.TEMPO_LIMITE_SEGUNDOS
        yield _Resposta(mensagem)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert buscar("https://h/") == [
        ("x-frame-options", "DENY"),
        ("content-security-policy", "default-src 'self' 'unsafe-inline'"),
        ("content-security-policy", "default-src 'none'"),
    ]


def test_cabecalho_de_seguranca_repetido_reprova() -> None:
    """O estado real da borda durante a troca de regras: o /docs recebia o CSP antigo
    (com 'unsafe-inline') e o novo, e só o último era conferido."""

    def busca(url: str) -> list[tuple[str, str]]:
        csp = CSP_DOCS if url.endswith(("/docs", "/redoc")) else CSP_API
        itens = list(_bons(csp).items())
        if url.endswith("/docs"):
            itens.insert(0, ("content-security-policy", CSP_DOCS_ANTIGA))
            itens.append(("referrer-policy", "no-referrer"))
        return itens

    falhas = [v for v in verificar("https://h/b3datetime", busca) if not v.ok]
    assert [(v.pagina, v.cabecalho) for v in falhas] == [
        ("/docs", "content-security-policy (repetido)"),
        ("/docs", "referrer-policy (repetido)"),
    ]
    assert falhas[0].valor == f"{CSP_DOCS_ANTIGA} ‖ {CSP_DOCS}"
    assert "Add em vez de Set" in falhas[0].motivo


def test_cabecalho_que_nao_e_de_seguranca_pode_repetir() -> None:
    itens = [*_bons().items(), ("vary", "Origin"), ("vary", "Accept-Encoding")]
    assert borda.repetidos("/", itens) == []
