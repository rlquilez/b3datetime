"""O gate da mutação (``scripts/mutation_gate.py``).

Um gate de mutação que calcula errado é pior que nenhum: dá um número bonito a uma suíte
que não testa nada. Os casos que mais importam são os de score "vazio" — zero mutantes
avaliados ou zero detectados —, que é o que um run quebrado produz.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.mutation_gate import RAIZ, Resultado, limiar, main, problemas, resultado, sobreviventes


def test_score_conta_timeout_e_segfault_como_detectados() -> None:
    res = resultado(
        {
            "killed": 90,
            "timeout": 3,
            "segfault": 1,
            "survived": 4,
            "no_tests": 1,
            "suspicious": 1,
            "skipped": 7,
        }
    )
    assert res == Resultado(detectados=94, avaliados=100)
    assert res.score == 94.0


@pytest.mark.parametrize(
    ("res", "trecho"),
    [
        (Resultado(detectados=0, avaliados=0), "nenhum mutante avaliado"),
        (Resultado(detectados=0, avaliados=10), "nenhum mutante detectado"),
        (Resultado(detectados=89, avaliados=100), "abaixo do limiar"),
    ],
)
def test_reprovacoes(res: Resultado, trecho: str) -> None:
    assert any(trecho in p for p in problemas(res, 90.0))


def test_no_limiar_exato_aprova() -> None:
    assert problemas(Resultado(detectados=90, avaliados=100), 90.0) == []


def test_limiar_vem_do_pyproject() -> None:
    assert 0 < limiar(RAIZ / "pyproject.toml") <= 100


def test_sobreviventes_da_saida_do_mutmut() -> None:
    saida = (
        "    b3datetime.config.x_redact_url__mutmut_3: survived\n"
        "    b3datetime.main.x_create_app__mutmut_9: killed\n"
        "    b3datetime.dates.x_f__mutmut_1: no tests\n"
    )
    assert sobreviventes(saida) == [
        "b3datetime.config.x_redact_url__mutmut_3",
        "b3datetime.dates.x_f__mutmut_1",
    ]


def test_main_escreve_o_resumo_e_aprova(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"killed": 999, "survived": 1}))
    saida = tmp_path / "sobreviventes.txt"
    saida.write_text("    b3datetime.x__mutmut_1: survived\n")
    resumo = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumo))
    assert main([str(stats), str(saida)]) == 0
    texto = resumo.read_text()
    assert "Score: 99.90%" in texto
    assert "b3datetime.x__mutmut_1" in texto


def test_main_reprova_run_sem_mutantes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"killed": 0, "survived": 0}))
    saida = tmp_path / "sobreviventes.txt"
    saida.write_text("")
    assert main([str(stats), str(saida)]) == 1


def test_main_sem_argumentos_e_erro_de_uso() -> None:
    assert main([]) == 2
