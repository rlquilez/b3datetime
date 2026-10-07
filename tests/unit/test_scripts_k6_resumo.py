"""O tripwire do teste de carga (``scripts/k6_resumo.py``) e a cobertura do script do k6.

O risco que o tripwire fecha: um limiar de p95 sobre um endpoint que nunca recebeu
requisição passa em silêncio — o p95 de nenhuma amostra é zero.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.k6_resumo import (
    caminhos_do_contrato,
    endpoints_do_script,
    limiares_cruzados,
    main,
    problemas,
    resumo,
)

RAIZ = Path(__file__).resolve().parents[2]
SMOKE = RAIZ / "tests" / "load" / "smoke.js"
CONTRATO = RAIZ / "tests" / "contract" / "openapi.json"

SCRIPT = """\
const ENDPOINTS = {
  raiz: { caminho: '/' },
  periodo: { caminho: '/v1/trading-days', consulta: (j) => `start=${j.inicio}` },
};
"""


def _duracao(maximo: float, cruzado: bool = False) -> dict[str, Any]:
    return {
        "med": 1.0,
        "p(95)": 2.0,
        "p(99)": 3.0,
        "max": maximo,
        "thresholds": {"p(95)<250": cruzado},
    }


def _metricas(**extra: Any) -> dict[str, Any]:
    return {
        "http_reqs": {"count": 100, "rate": 10.0},
        "http_req_failed": {"passes": 0, "fails": 100, "thresholds": {"rate==0": False}},
        "dropped_iterations": {"count": 0, "thresholds": {"count==0": False}},
        "health_sob_carga_relativo": {"p(95)": 1.5, "thresholds": {"p(95)<5": False}},
        "http_req_duration{endpoint:raiz}": _duracao(5.0),
        "http_req_duration{endpoint:periodo}": _duracao(4.0),
        **extra,
    }


def test_o_script_do_k6_cobre_toda_operacao_do_contrato() -> None:
    """Endpoint novo no contrato sem cenário de carga reprova aqui, antes do CI."""
    endpoints = endpoints_do_script(SMOKE.read_text(encoding="utf-8"))
    contrato = caminhos_do_contrato(json.loads(CONTRATO.read_text(encoding="utf-8")))
    assert set(endpoints.values()) == contrato


def test_endpoints_do_script() -> None:
    assert endpoints_do_script(SCRIPT) == {"raiz": "/", "periodo": "/v1/trading-days"}


def test_caminhos_do_contrato_ignoram_chaves_que_nao_sao_metodo() -> None:
    contrato = {"paths": {"/a": {"get": {}}, "/b": {"parameters": []}}}
    assert caminhos_do_contrato(contrato) == {"/a"}


def test_limiares_cruzados() -> None:
    metricas = _metricas(**{"http_req_duration{endpoint:raiz}": _duracao(5.0, cruzado=True)})
    assert limiares_cruzados(metricas) == ["http_req_duration{endpoint:raiz}: p(95)<250"]


def test_tudo_em_ordem_aprova() -> None:
    assert problemas(_metricas(), endpoints_do_script(SCRIPT), {"/", "/v1/trading-days"}) == []


def test_endpoint_sem_requisicao_reprova() -> None:
    """O caso que o k6 sozinho não pega: p95 de nenhuma amostra passa no limiar."""
    metricas = _metricas(**{"http_req_duration{endpoint:periodo}": _duracao(0.0)})
    erros = problemas(metricas, endpoints_do_script(SCRIPT), {"/", "/v1/trading-days"})
    assert erros == ["periodo (/v1/trading-days) não recebeu nenhuma requisição"]


def test_metrica_ausente_tambem_reprova() -> None:
    metricas = _metricas()
    del metricas["http_req_duration{endpoint:raiz}"]
    erros = problemas(metricas, endpoints_do_script(SCRIPT), {"/", "/v1/trading-days"})
    assert erros == ["raiz (/) não recebeu nenhuma requisição"]


def test_operacao_do_contrato_sem_cenario_reprova() -> None:
    erros = problemas(_metricas(), endpoints_do_script(SCRIPT), {"/", "/v1/trading-days", "/v1/x"})
    assert erros == ["/v1/x está no contrato e não tem cenário no k6"]


def test_script_sem_endpoints_reprova() -> None:
    assert any("tripwire estaria vazio" in e for e in problemas(_metricas(), {}, set()))


def test_limiar_cruzado_reprova_independente_do_k6() -> None:
    metricas = _metricas(dropped_iterations={"count": 3, "thresholds": {"count==0": True}})
    erros = problemas(metricas, endpoints_do_script(SCRIPT), {"/", "/v1/trading-days"})
    assert erros == ["limiar cruzado — dropped_iterations: count==0"]


def test_resumo() -> None:
    metricas = _metricas(**{"http_req_duration{endpoint:caro}": _duracao(9.0, cruzado=True)})
    texto = resumo(metricas, endpoints_do_script(SCRIPT))
    assert "**100 requisições** (10.0/s) · falhas: 0 · iterações descartadas: 0" in texto
    assert "health sob carga: p95 = 1.50 vezes o ocioso" in texto
    assert "| raiz | `/` | 1.0 ms | 2.0 ms | 3.0 ms | 5.0 ms | ✅ p(95)<250 |" in texto
    assert "| caro | `/v1/trading-days?…&exclude=true` |" in texto
    assert "❌ p(95)<250" in texto


def test_resumo_sem_metricas_nao_quebra() -> None:
    texto = resumo({}, {"raiz": "/"})
    assert "**0 requisições**" in texto
    assert "| raiz | `/` | — | — | — | — | — |" in texto


def test_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    resultado = tmp_path / "k6.json"
    resultado.write_text(json.dumps({"metrics": _metricas()}))
    script = tmp_path / "smoke.js"
    script.write_text(SCRIPT)
    contrato = tmp_path / "openapi.json"
    contrato.write_text(json.dumps({"paths": {"/": {"get": {}}, "/v1/trading-days": {"get": {}}}}))
    sumario = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(sumario))

    assert main([str(resultado), str(script), str(contrato)]) == 0
    assert "## Performance · k6" in sumario.read_text(encoding="utf-8")

    monkeypatch.delenv("GITHUB_STEP_SUMMARY")
    resultado.write_text(json.dumps({"metrics": {}}))
    assert main([str(resultado), str(script), str(contrato)]) == 1
    assert "::error::raiz (/) não recebeu nenhuma requisição" in capsys.readouterr().out


def test_main_com_argumentos_errados() -> None:
    assert main([]) == 2
