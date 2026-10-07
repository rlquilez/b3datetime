"""Imagens fixadas por digest: o Redis dos testes e as bases dos Dockerfiles.

A imagem do Redis dos testes é uma só, fixada por digest, em todo lugar.

A fonte é ``tests/stack/compose.yaml`` — o Dependabot (ecossistema ``docker-compose``)
propõe o digest novo ali. O E2E e o smoke test a leem de lá; o service do CI não tem como
ler um arquivo, então este teste exige que ele repita o mesmo valor. Quando o Dependabot
atualizar o compose, este teste aponta o ``ci.yml`` que ficou para trás.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
REDIS = re.compile(r"(redis:[\w.-]+@sha256:[0-9a-f]{64})")


def _imagens(caminho: Path) -> set[str]:
    return set(REDIS.findall(caminho.read_text(encoding="utf-8")))


def test_a_fonte_fixa_o_redis_por_digest() -> None:
    assert len(_imagens(RAIZ / "tests" / "stack" / "compose.yaml")) == 1


def test_o_ci_usa_o_mesmo_redis_da_fonte() -> None:
    fonte = _imagens(RAIZ / "tests" / "stack" / "compose.yaml")
    assert _imagens(RAIZ / ".github" / "workflows" / "ci.yml") == fonte


def test_e2e_e_smoke_leem_da_fonte_sem_tag_solta() -> None:
    """Nenhuma referência ao Redis por tag mutável (``redis:7.4-alpine`` sem digest)."""
    for caminho in (RAIZ / "tests" / "e2e" / "conftest.py", RAIZ / "scripts" / "smoke_image.sh"):
        texto = caminho.read_text(encoding="utf-8")
        assert "tests/stack/compose.yaml" in texto or '"stack" / "compose.yaml"' in texto, caminho
        # Versão com ponto (7.4-alpine), não porta (:6379); quantificador possessivo para o
        # lookahead não "achar" um prefixo da tag que não seja seguido de @.
        assert not re.search(r"\bredis:\d+\.\d[\w.-]*+(?!@)", texto), caminho


# --- Imagens base dos Dockerfiles ------------------------------------------------------

DOCKERFILES = [RAIZ / "Dockerfile", *sorted((RAIZ / "tests").rglob("Dockerfile"))]
FROM = re.compile(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)", re.MULTILINE)


def _dir_do_dependabot(dockerfile: Path) -> str:
    return "/" + dockerfile.parent.relative_to(RAIZ).as_posix().removeprefix(".")


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=_dir_do_dependabot)
def test_toda_imagem_base_e_fixada_por_digest(dockerfile: Path) -> None:
    """Tag mutável na base muda a imagem sem commit: o que o CI escaneou deixa de ser o
    que roda. Vale também para ferramentas, como o ZAP do DAST (tests/dast/Dockerfile)."""
    bases = FROM.findall(dockerfile.read_text(encoding="utf-8"))
    assert bases, dockerfile
    for base in bases:
        assert re.fullmatch(r"[\w./:-]+:[\w.-]+@sha256:[0-9a-f]{64}", base), base


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=_dir_do_dependabot)
def test_dependabot_acompanha_cada_dockerfile(dockerfile: Path) -> None:
    """Um digest fixado sem Dependabot congela a imagem — e as correções de segurança dela."""
    config = yaml.safe_load((RAIZ / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    docker = [u for u in config["updates"] if u["package-ecosystem"] == "docker"]
    diretorios = {d for u in docker for d in u.get("directories", [u.get("directory")])}
    assert _dir_do_dependabot(dockerfile) in diretorios
