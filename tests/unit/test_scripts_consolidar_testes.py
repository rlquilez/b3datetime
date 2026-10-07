"""O gate que consolida os blocos de teste (``scripts/consolidar_testes.py``).

Um tripwire que não dispara é pior do que nenhum: ele dá a falsa garantia de que a
suíte inteira rodou. Cada condição de reprovação é exercitada aqui.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.consolidar_testes import Bloco, ler_junit, main, problemas, tabela

COBERTURA_OK = '<coverage><class filename="src/b3datetime/main.py"/></coverage>'


def _junit(tmp_path: Path, bloco: str, **atributos: object) -> Path:
    valores = {"tests": 3, "failures": 0, "errors": 0, "skipped": 0, "time": 1.5} | atributos
    attrs = " ".join(f'{k}="{v}"' for k, v in valores.items())
    caminho = tmp_path / f"junit-{bloco}.xml"
    caminho.write_text(
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest" {attrs}/></testsuites>',
        encoding="utf-8",
    )
    return caminho


def test_le_totais_e_nome_do_bloco(tmp_path: Path) -> None:
    bloco = ler_junit(_junit(tmp_path, "integration", tests=7, skipped=1, time=2.25))
    assert bloco == Bloco("integration", testes=7, falhas=0, erros=0, pulados=1, segundos=2.25)


def test_le_testsuite_na_raiz(tmp_path: Path) -> None:
    caminho = tmp_path / "junit-unit.xml"
    caminho.write_text('<testsuite tests="4" failures="1" errors="0" skipped="0"/>')
    assert ler_junit(caminho).testes == 4
    assert ler_junit(caminho).falhas == 1


def test_tudo_em_ordem_nao_tem_problemas() -> None:
    assert problemas([Bloco("unit", 10, 0, 0, 0, 1.0)], COBERTURA_OK) == []


@pytest.mark.parametrize(
    ("blocos", "cobertura", "trecho"),
    [
        ([], COBERTURA_OK, "nenhum relatório"),
        ([Bloco("unit", 0, 0, 0, 0, 0.0)], COBERTURA_OK, "não executou nenhum teste"),
        ([Bloco("integration", 5, 0, 0, 2, 1.0)], COBERTURA_OK, "pulou 2 teste(s)"),
        ([Bloco("unit", 5, 1, 0, 0, 1.0)], COBERTURA_OK, "1 falha(s)"),
        ([Bloco("unit", 5, 0, 0, 0, 1.0)], '<class filename="/home/x/src/a.py"/>', "0%"),
    ],
)
def test_cada_violacao_e_reportada(blocos: list[Bloco], cobertura: str, trecho: str) -> None:
    erros = problemas(blocos, cobertura)
    assert any(trecho in erro for erro in erros), erros


def test_tabela_tem_uma_linha_por_bloco_e_o_total() -> None:
    texto = tabela([Bloco("api", 2, 0, 0, 0, 0.5), Bloco("unit", 3, 0, 0, 0, 0.25)])
    assert "| api | 2 |" in texto
    assert "| unit | 3 |" in texto
    assert "**5**" in texto


def test_main_reprova_com_pulo_e_escreve_o_resumo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cobertura = tmp_path / "coverage.xml"
    cobertura.write_text(COBERTURA_OK)
    resumo = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumo))

    codigo = main([str(cobertura), str(_junit(tmp_path, "unit", skipped=1))])

    assert codigo == 1
    assert "::error::o bloco 'unit' pulou 1 teste(s)" in capsys.readouterr().out
    assert "| unit | 3 |" in resumo.read_text()


def test_main_aprova_quando_tudo_rodou(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    cobertura = tmp_path / "coverage.xml"
    cobertura.write_text(COBERTURA_OK)
    assert main([str(cobertura), str(_junit(tmp_path, "unit")), str(_junit(tmp_path, "api"))]) == 0


def test_main_sem_argumentos_e_erro_de_uso() -> None:
    assert main([]) == 2
