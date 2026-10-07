"""O tripwire do DAST (``scripts/dast_resumo.py``).

O caso que motivou o script: uma varredura que "passa" sem ter atacado a lógica. Antes
dos exemplos de parâmetro, o ZAP alcançava ``/v1/trading-days`` só com ``start=start`` —
422 em toda requisição — e nenhum alerta aparecia porque nada era exercitado.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.dast_resumo import (
    Alerta,
    No,
    Operacao,
    alertas,
    main,
    nao_alcancadas,
    nos,
    operacoes,
    problemas,
    resumo,
)

RAIZ = Path(__file__).resolve().parents[2]

CONTRATO: dict[str, Any] = {
    "servers": [{"url": "/b3datetime"}],
    "paths": {
        "/": {"get": {}},
        "/v1/trading-days": {"get": {}, "parameters": []},
        "/v1/itens/{item}": {"get": {}, "delete": {}},
    },
}

ARVORE_YAML = """\
- node: Sites
  children:
  - node: http://app:8000
    children:
    - node: GET:b3datetime
      url: http://app:8000/b3datetime/
      method: GET
      statusCode: 200
    - node: v1
      url: http://app:8000/b3datetime/v1
      method: GET
      children:
      - node: "GET:trading-days(end,start)"
        url: http://app:8000/b3datetime/v1/trading-days?start=start&end=end
        method: GET
        statusCode: 422
      - node: GET:itens
        url: http://app:8000/b3datetime/v1/itens/42
        method: GET
        statusCode: 200
"""


def _alerta(regra: str, risco: str, confianca: str = "2") -> dict[str, Any]:
    return {
        "pluginid": regra,
        "name": f"regra {regra}",
        "riskcode": risco,
        "confidence": confianca,
        "count": "1",
    }


def test_operacoes_do_contrato_levam_o_prefixo_e_ignoram_chaves_que_nao_sao_metodo() -> None:
    assert operacoes(CONTRATO) == [
        Operacao("DELETE", "/b3datetime/v1/itens/{item}"),
        Operacao("GET", "/b3datetime/"),
        Operacao("GET", "/b3datetime/v1/itens/{item}"),
        Operacao("GET", "/b3datetime/v1/trading-days"),
    ]


def test_sem_servers_o_caminho_fica_como_esta() -> None:
    assert operacoes({"paths": {"/v1/x": {"get": {}}}}) == [Operacao("GET", "/v1/x")]


def test_nos_estruturais_sem_status_ficam_de_fora() -> None:
    assert sorted(nos(yaml.safe_load(ARVORE_YAML)), key=lambda n: n.caminho) == [
        No("GET", "/b3datetime/", 200),
        No("GET", "/b3datetime/v1/itens/42", 200),
        No("GET", "/b3datetime/v1/trading-days", 422),
    ]


def test_arvore_vazia_ou_nula() -> None:
    assert nos(None) == []
    assert nos([]) == []


def test_operacao_que_so_alcancou_a_validacao_nao_conta() -> None:
    """O caso real: 422 em todas as requisições de /v1/trading-days."""
    faltando = nao_alcancadas(operacoes(CONTRATO), nos(yaml.safe_load(ARVORE_YAML)))
    assert faltando == [
        Operacao("DELETE", "/b3datetime/v1/itens/{item}"),
        Operacao("GET", "/b3datetime/v1/trading-days"),
    ]


@pytest.mark.parametrize(
    ("caminho", "casa"),
    [
        ("/b3datetime/v1/itens/42", True),
        ("/b3datetime/v1/itens/42/extra", False),
        ("/b3datetime/v1/itens/", False),
    ],
)
def test_parametro_de_caminho_casa_exatamente_um_segmento(caminho: str, casa: bool) -> None:
    op = Operacao("GET", "/b3datetime/v1/itens/{item}")
    assert (nao_alcancadas([op], [No("GET", caminho, 200)]) == []) is casa


@pytest.mark.parametrize("status", [199, 300, 404, 500])
def test_so_2xx_conta_como_alcancada(status: int) -> None:
    op = Operacao("GET", "/x")
    assert nao_alcancadas([op], [No("GET", "/x", status)]) == [op]


def test_metodo_diferente_nao_conta() -> None:
    op = Operacao("DELETE", "/x")
    assert nao_alcancadas([op], [No("GET", "/x", 200)]) == [op]


def test_alertas_e_o_que_reprova() -> None:
    lista = alertas(
        {
            "site": [
                {
                    "alerts": [
                        _alerta("10038", "0"),
                        _alerta("10096", "1", confianca="0"),
                        _alerta("10003", "2"),
                        _alerta("40018", "3"),
                    ]
                }
            ]
        }
    )
    assert [(a.regra, a.falso_positivo, a.reprova) for a in lista] == [
        ("10038", False, False),
        ("10096", True, False),
        ("10003", False, True),
        ("40018", False, True),
    ]


def test_relatorio_sem_sites() -> None:
    assert alertas({}) == []


def test_problemas_de_tripwire_vazio() -> None:
    erros = problemas([], [], [])
    assert any("contrato não tem operações" in e for e in erros)
    assert any("árvore de sites está vazia" in e for e in erros)


def test_problemas_listam_operacoes_e_alertas() -> None:
    op = Operacao("GET", "/x")
    alerta = Alerta("10003", "Vulnerable JS Library", "2", "2", 1)
    erros = problemas([op], [No("GET", "/x", 422)], [alerta])
    assert erros == [
        "GET /x não foi alcançada com resposta 2xx pela varredura",
        "alerta Médio não filtrado: 10003 Vulnerable JS Library",
    ]


def test_tudo_alcancado_e_so_informativos_aprova() -> None:
    op = Operacao("GET", "/x")
    info = Alerta("10038", "CSP", "0", "3", 2)
    falso = Alerta("10096", "Timestamp", "1", "0", 0)
    assert problemas([op], [No("GET", "/x", 200)], [info, falso]) == []


def test_resumo_ordena_por_risco_e_marca_operacoes() -> None:
    ops = [Operacao("GET", "/a"), Operacao("GET", "/b")]
    lista = [
        Alerta("10096", "Timestamp", "1", "0", 0),
        Alerta("10038", "CSP", "0", "3", 2),
        Alerta("10003", "Vulnerable JS Library", "2", "2", 1),
    ]
    texto = resumo(ops, [No("GET", "/a", 200)], lista)
    assert "**1 de 2 operações do contrato alcançadas com 2xx** · 1 nós" in texto
    tabela = [
        linha for linha in texto.splitlines() if linha.startswith("| ") and "Regra" not in linha
    ]
    assert tabela == [
        "| Médio | 10003 | Vulnerable JS Library | 1 |",
        "| Informativo | 10038 | CSP | 2 |",
        "| Falso positivo (filtrado) | 10096 | Timestamp | 0 |",
    ]
    assert "- ✅ `GET /a`" in texto
    assert "- ❌ `GET /b`" in texto


def test_resumo_sem_alertas() -> None:
    assert "| — | — | nenhum alerta | 0 |" in resumo([], [], [])


def test_main_aprova_e_escreve_o_resumo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    relatorio = tmp_path / "zap.json"
    relatorio.write_text(json.dumps({"site": [{"alerts": [_alerta("10038", "0")]}]}))
    arvore = tmp_path / "arvore.yaml"
    arvore.write_text(
        "- node: Sites\n  children:\n  - node: GET:x\n"
        "    url: http://app:8000/b3datetime/x\n    method: GET\n    statusCode: 200\n"
    )
    contrato = tmp_path / "openapi.json"
    contrato.write_text(
        json.dumps({"servers": [{"url": "/b3datetime"}], "paths": {"/x": {"get": {}}}})
    )
    sumario = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(sumario))

    assert main([str(relatorio), str(arvore), str(contrato)]) == 0
    assert "**1 de 1 operações" in sumario.read_text(encoding="utf-8")


def test_main_reprova_com_o_contrato_real_e_arvore_vazia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    relatorio = tmp_path / "zap.json"
    relatorio.write_text("{}")
    arvore = tmp_path / "arvore.yaml"
    arvore.write_text("[]")

    contrato = RAIZ / "tests" / "contract" / "openapi.json"
    assert main([str(relatorio), str(arvore), str(contrato)]) == 1
    assert "::error::GET /b3datetime/v1/trading-days não foi alcançada" in capsys.readouterr().out


def test_main_com_argumentos_errados() -> None:
    assert main([]) == 2
