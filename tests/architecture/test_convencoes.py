"""Convenções do CLAUDE.md transformadas em regras executáveis, sobre a AST do pacote.

Cada regra aqui já foi um bug ou uma armadilha documentada; escrita em prosa, dependia de
alguém lembrar. As regras de dependência entre módulos ficam no import-linter
(``[tool.importlinter]`` no ``pyproject.toml``); estas são as que a análise de imports
não alcança.
"""

from __future__ import annotations

import ast
import importlib
import re
import tomllib
from pathlib import Path

import pytest
from fastapi import APIRouter

from b3datetime.config import Settings
from b3datetime.main import create_app
from tests.api.test_openapi import _api_routes

RAIZ = Path(__file__).resolve().parents[2]
PACOTE = RAIZ / "src" / "b3datetime"
MODULOS = sorted(p for p in PACOTE.rglob("*.py") if "__pycache__" not in p.parts)
ROUTERS = ("hours", "dates", "health", "root")


def _arvore(caminho: Path) -> ast.Module:
    return ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))


def _nome(caminho: Path) -> str:
    return caminho.relative_to(PACOTE.parent).with_suffix("").as_posix().replace("/", ".")


def _chamadas(no: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(no) if isinstance(n, ast.Call)]


def _nome_chamado(chamada: ast.Call) -> str:
    alvo = chamada.func
    if isinstance(alvo, ast.Name):
        return alvo.id
    if isinstance(alvo, ast.Attribute):
        return alvo.attr
    return ""


@pytest.mark.parametrize("caminho", MODULOS, ids=_nome)
def test_nada_instancia_settings_nem_cria_a_app_em_nivel_de_modulo(caminho: Path) -> None:
    """Instanciar no import lia o ambiente e o ``.env`` — e um ``TIMEZONE`` inválido
    derrubava o import antes de qualquer log (#60). Vale para ``Settings()``,
    ``get_settings()`` e ``create_app()`` fora de funções."""
    proibidas = {"Settings", "get_settings", "create_app"}
    for no in _arvore(caminho).body:
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        chamadas = {_nome_chamado(c) for c in _chamadas(no)} & proibidas
        assert not chamadas, f"{_nome(caminho)} chama {chamadas} no import"


@pytest.mark.parametrize("caminho", MODULOS, ids=_nome)
def test_settings_nunca_vem_do_get_settings_global_via_depends(caminho: Path) -> None:
    """``SettingsDep`` resolve ``request.app.state.settings``. ``Depends(get_settings)``
    aplicava as settings do ambiente em vez das da app (#60)."""
    for chamada in _chamadas(_arvore(caminho)):
        if _nome_chamado(chamada) == "Depends" and chamada.args:
            alvo = chamada.args[0]
            assert not (isinstance(alvo, ast.Name) and alvo.id == "get_settings"), _nome(caminho)


def test_servicos_so_sao_construidos_no_lifespan() -> None:
    """Nenhum I/O fora do lifespan: o serviço de Redis e o calendário real são construídos
    só dentro de ``lifespan`` (``main.py``) — nunca em router, dependência ou import."""
    construtores = {"RedisService", "build_bvmf_calendar"}
    for caminho in MODULOS:
        arvore = _arvore(caminho)
        permitidas: set[int] = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.AsyncFunctionDef) and no.name == "lifespan":
                permitidas |= {id(c) for c in _chamadas(no)}
        for chamada in _chamadas(arvore):
            if _nome_chamado(chamada) in construtores:
                assert id(chamada) in permitidas, (
                    f"{_nome(caminho)} constrói {_nome_chamado(chamada)} fora do lifespan"
                )


def test_modelos_de_resposta_so_sao_usados_no_router_que_os_declara() -> None:
    """Convenção: o modelo Pydantic de resposta vive no router que o usa. Um modelo
    importado por outro router acopla os contratos de dois endpoints."""
    declarados: dict[str, str] = {}
    for nome in ROUTERS:
        arvore = _arvore(PACOTE / "routers" / f"{nome}.py")
        for no in arvore.body:
            if isinstance(no, ast.ClassDef) and any(
                isinstance(b, ast.Name) and b.id == "BaseModel" for b in no.bases
            ):
                declarados[no.name] = nome
    assert declarados, "nenhum modelo de resposta encontrado: a regra estaria vazia"
    for caminho in MODULOS:
        for importacao in ast.walk(_arvore(caminho)):
            if isinstance(importacao, ast.ImportFrom) and (importacao.module or "").startswith(
                "b3datetime.routers."
            ):
                usados = {alias.name for alias in importacao.names} & declarados.keys()
                assert not usados, f"{_nome(caminho)} importa {usados} de {importacao.module}"


@pytest.mark.parametrize("nome", ROUTERS)
def test_todo_router_esta_incluido_na_app(nome: str) -> None:
    """Um router declarado e não incluído em ``create_app`` é código morto que parece vivo."""
    modulo = importlib.import_module(f"b3datetime.routers.{nome}")
    router = modulo.router
    assert isinstance(router, APIRouter)
    publicadas = {r.path for r in _api_routes(create_app(Settings(_env_file=None)).routes)}
    for rota in _api_routes(router.routes):
        assert rota.path in publicadas, f"{nome}: {rota.path} não está publicada"


def test_routers_conhecidos_sao_todos_os_que_existem() -> None:
    """Se um router novo aparecer, ele precisa entrar nas regras acima (e em DOCUMENTED_CODES)."""
    existentes = {
        p.stem
        for p in (PACOTE / "routers").glob("*.py")
        if p.stem not in {"__init__", "openapi_examples"}
    }
    assert existentes == set(ROUTERS)


def test_sandbox_da_mutacao_tem_todo_arquivo_que_os_testes_leem() -> None:
    """O mutmut roda a suíte dentro de ``mutants/``, que só recebe ``src/``, ``tests/``, o
    ``pyproject.toml`` e o ``also_copy``. Um teste que lê um arquivo do repositório fora
    disso reprova a execução limpa e derruba o job inteiro antes de avaliar mutante algum
    — foi o que aconteceu no push de #67, com ``.github/workflows/ci.yml``."""
    config = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    copiados = {"src", "tests", "pyproject.toml"} | {
        caminho.rstrip("/") for caminho in config["tool"]["mutmut"]["also_copy"]
    }
    leitura = re.compile(r'\b(?:RAIZ|REPO_ROOT)\s*/\s*"([^"/]+)"')
    lidos = {
        nome
        for arquivo in [*(RAIZ / "tests").rglob("*.py"), *(RAIZ / "scripts").glob("*.py")]
        for nome in leitura.findall(arquivo.read_text(encoding="utf-8"))
    }
    assert {".github", "Dockerfile"} <= lidos, "o padrão de busca deixou de achar as leituras"
    assert lidos <= copiados, f"lidos pelos testes e fora do sandbox: {lidos - copiados}"
