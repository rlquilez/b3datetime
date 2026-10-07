"""A imagem do Redis dos testes é uma só, fixada por digest, em todo lugar.

A fonte é ``tests/stack/compose.yaml`` — o Dependabot (ecossistema ``docker-compose``)
propõe o digest novo ali. O E2E e o smoke test a leem de lá; o service do CI não tem como
ler um arquivo, então este teste exige que ele repita o mesmo valor. Quando o Dependabot
atualizar o compose, este teste aponta o ``ci.yml`` que ficou para trás.
"""

from __future__ import annotations

import re
from pathlib import Path

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
