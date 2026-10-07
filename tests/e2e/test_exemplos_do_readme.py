"""Os exemplos do README funcionam como estão escritos.

O README documenta cada endpoint com cURL e Python contra a URL pública, e o CLAUDE.md
pedia para rodá-los à mão depois de mexer num endpoint. Este teste os executa: cada bloco
``bash``/``python`` que usa a URL pública roda de verdade — os ``curl`` por subprocesso, os
programas Python com o interpretador da suíte —, trocando só a URL pela do ambiente sob
teste. Contra a imagem (``E2E_IMAGE``) a troca aponta para o container; contra a produção
(``E2E_BASE_URL``) a URL é a mesma e os exemplos rodam literalmente.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.e2e.conftest import Ambiente

pytestmark = pytest.mark.e2e

README = Path(__file__).resolve().parents[2] / "README.md"
URL_PUBLICA = "https://api.quilez.cloud/b3datetime"
BLOCO = re.compile(r"^```(bash|python)\n(.*?)^```", re.DOTALL | re.MULTILINE)


class Exemplo(NamedTuple):
    linguagem: str
    linha: int
    codigo: str


def _exemplos() -> list[Exemplo]:
    texto = README.read_text(encoding="utf-8")
    exemplos = []
    for bloco in BLOCO.finditer(texto):
        linguagem, codigo = bloco.group(1), bloco.group(2)
        # Só os exemplos de uso da API (os comandos de desenvolvimento não usam a URL);
        # a linha de pytest contra a produção é documentação do próprio E2E.
        if URL_PUBLICA in codigo and "pytest" not in codigo:
            linha = texto.count("\n", 0, bloco.start()) + 1
            exemplos.append(Exemplo(linguagem, linha, codigo))
    return exemplos


EXEMPLOS = _exemplos()


def test_o_readme_tem_exemplos_de_curl_e_de_python() -> None:
    """Se a extração parar de achar exemplos, a suíte abaixo vira um conjunto vazio."""
    assert {e.linguagem for e in EXEMPLOS} == {"bash", "python"}
    assert len(EXEMPLOS) >= 10


def _rodar(comando: list[str], entrada: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - comandos tirados do README versionado
        comando, input=entrada, capture_output=True, text=True, timeout=60, check=False
    )


@pytest.mark.parametrize("exemplo", EXEMPLOS, ids=lambda e: f"README.md:{e.linha}-{e.linguagem}")
def test_exemplo_do_readme_funciona(exemplo: Exemplo, principal: Ambiente) -> None:
    base = str(principal.http.base_url).rstrip("/")
    codigo = exemplo.codigo.replace(URL_PUBLICA, base)

    if exemplo.linguagem == "python":
        proc = _rodar([sys.executable, "-"], entrada=codigo)
        assert proc.returncode == 0, f"README.md:{exemplo.linha}\n{proc.stderr}"
        assert proc.stdout.strip(), "o exemplo deveria imprimir algo"
        return

    comandos = [linha for linha in codigo.splitlines() if linha.startswith("curl ")]
    assert comandos, f"README.md:{exemplo.linha} sem comando curl"
    for comando in comandos:
        proc = _rodar(shlex.split(comando))
        assert proc.returncode == 0, f"{comando}\n{proc.stderr}"
        json.loads(proc.stdout)  # a resposta documentada é JSON
