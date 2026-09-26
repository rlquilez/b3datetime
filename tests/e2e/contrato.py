"""Contrato publicado: o ``/openapi.json`` que o próprio container serve.

A suíte E2E não confia em nada escrito à mão sobre a API. As operações, os códigos de
resposta e os schemas vêm do documento servido, e cada resposta é validada contra ele:

- com ``schema`` documentado (200, 422 e o 503 do health), por JSON Schema 2020-12 — o
  dialeto do OpenAPI 3.1 —, com os ``$ref`` resolvidos contra o documento inteiro;
- só com exemplo (os envelopes de erro 400/404/502/503), pela forma do exemplo: nenhum
  campo fora do documentado, tipos compatíveis e a mesma categoria de ``error``.
"""

from __future__ import annotations

from typing import Any

import httpx
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

URI = "urn:b3datetime:openapi"
JSON = "application/json"


def _ponteiro(*partes: str) -> str:
    """JSON Pointer (RFC 6901): ``/v1/hours`` vira ``~1v1~1hours``."""
    return "/".join(parte.replace("~", "~0").replace("/", "~1") for parte in partes)


def _forma(corpo: Any, exemplo: Any, onde: str = "$") -> list[str]:
    """Diferenças de forma entre o corpo e um exemplo documentado.

    Campos ausentes no corpo são aceitos — o exemplo de 503 dos horários traz
    ``cache_age_seconds``, que só existe quando há cache —, mas campo que o exemplo não
    documenta, não. ``null`` no exemplo não restringe o tipo.
    """
    if exemplo is None:
        return []
    if isinstance(exemplo, dict):
        if not isinstance(corpo, dict):
            return [f"{onde}: esperado objeto, veio {type(corpo).__name__}"]
        problemas = [f"{onde}.{k}: campo não documentado" for k in corpo if k not in exemplo]
        for chave in corpo.keys() & exemplo.keys():
            problemas += _forma(corpo[chave], exemplo[chave], f"{onde}.{chave}")
        return problemas
    if isinstance(exemplo, list):
        if not isinstance(corpo, list):
            return [f"{onde}: esperado lista, veio {type(corpo).__name__}"]
        return (
            [p for item in corpo[:1] for p in _forma(item, exemplo[0], f"{onde}[0]")]
            if exemplo
            else []
        )
    if isinstance(exemplo, bool) or isinstance(corpo, bool):
        ok = isinstance(exemplo, bool) and isinstance(corpo, bool)
    elif isinstance(exemplo, int | float):
        ok = isinstance(corpo, int | float)
    else:
        ok = isinstance(corpo, type(exemplo))
    return [] if ok else [f"{onde}: esperado {type(exemplo).__name__}, veio {corpo!r}"]


def _envelope_de_erro(corpo: Any, exemplo: Any) -> list[str]:
    """Um erro documentado como ``{"detail": {"error": ...}}`` precisa responder a mesma
    categoria de ``error`` e uma ``message`` não vazia."""
    esperado = exemplo.get("detail", {}).get("error") if isinstance(exemplo, dict) else None
    if esperado is None:
        return []
    detalhe = corpo.get("detail") if isinstance(corpo, dict) else None
    if not isinstance(detalhe, dict):
        return ["$.detail: envelope de erro ausente"]
    problemas = []
    if detalhe.get("error") != esperado:
        problemas.append(f"$.detail.error: esperado {esperado!r}, veio {detalhe.get('error')!r}")
    if not isinstance(detalhe.get("message"), str) or not detalhe["message"]:
        problemas.append("$.detail.message: ausente ou vazia")
    return problemas


class Contrato:
    """Operações, respostas e schemas do OpenAPI servido."""

    def __init__(self, documento: dict[str, Any]) -> None:
        self.documento = documento
        self._registro: Registry[Any] = Registry().with_resource(
            URI, Resource.from_contents(documento, default_specification=DRAFT202012)
        )

    def pares(self) -> set[tuple[str, str, str]]:
        """``(método, caminho, código)`` de cada resposta documentada."""
        return {
            (metodo.upper(), caminho, codigo)
            for caminho, operacoes in self.documento["paths"].items()
            for metodo, operacao in operacoes.items()
            for codigo in operacao["responses"]
        }

    def operacoes(self) -> set[tuple[str, str]]:
        """``(método, caminho)`` de cada operação publicada."""
        return {(metodo, caminho) for metodo, caminho, _ in self.pares()}

    def validar(self, metodo: str, caminho: str, resposta: httpx.Response) -> None:
        """Falha se a resposta não for uma das documentadas para a operação."""
        codigo = str(resposta.status_code)
        respostas = self.documento["paths"][caminho][metodo.lower()]["responses"]
        assert codigo in respostas, (
            f"{metodo} {caminho} respondeu {codigo}, que não está documentado: {resposta.text}"
        )
        conteudo = respostas[codigo]["content"][JSON]
        corpo = resposta.json()

        if "schema" in conteudo:
            ref = f"{URI}#/" + _ponteiro(
                "paths", caminho, metodo.lower(), "responses", codigo, "content", JSON, "schema"
            )
            validador = Draft202012Validator({"$ref": ref}, registry=self._registro)
            erros = [
                f"${''.join(f'.{parte}' for parte in erro.absolute_path)}: {erro.message}"
                for erro in validador.iter_errors(corpo)
            ]
            assert not erros, f"{metodo} {caminho} {codigo} fora do schema: {erros}"
            return

        if "example" in conteudo:
            exemplos = [conteudo["example"]]
        else:
            exemplos = [e["value"] for e in conteudo["examples"].values()]
        tentativas = [_forma(corpo, e) + _envelope_de_erro(corpo, e) for e in exemplos]
        assert any(not problemas for problemas in tentativas), (
            f"{metodo} {caminho} {codigo} não tem a forma de nenhum exemplo documentado: "
            f"{tentativas} — corpo: {corpo}"
        )
