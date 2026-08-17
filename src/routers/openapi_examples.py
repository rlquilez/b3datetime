"""Exemplos e blocos ``responses`` compartilhados da documentação OpenAPI.

Os três routers descreviam respostas de erro com dicionários estruturalmente idênticos.
Centralizá-los evita que a métrica de duplicação do SonarQube reprove o quality gate, e
garante que o corpo de erro documentado seja o mesmo em toda a API.
"""

from __future__ import annotations

from typing import Any


def error_response(description: str, example: dict[str, Any]) -> dict[str, Any]:
    """Monta uma entrada de `responses` com um único exemplo."""
    return {
        "description": description,
        "content": {"application/json": {"example": {"detail": example}}},
    }


def examples_response(description: str, examples: dict[str, Any]) -> dict[str, Any]:
    """Monta uma entrada de `responses` com exemplos nomeados."""
    return {
        "description": description,
        "content": {"application/json": {"examples": examples}},
    }


SERVICE_UNAVAILABLE_EXAMPLE = {
    "error": "Service Unavailable",
    "message": "Redis indisponível há mais de 3600s",
    "cache_age_seconds": 3700,
    "key": "b3:trading:hours:open",
}

KEY_NOT_FOUND_EXAMPLE = {
    "error": "Not Found",
    "message": "Chave não encontrada no Redis",
    "key": "b3:trading:hours:open",
}

CALENDAR_UNAVAILABLE_EXAMPLE = {
    "error": "Service Unavailable",
    "message": "Calendário de negociação indisponível",
}

RANGE_OUT_OF_BOUNDS_EXAMPLE = {
    "error": "Bad Request",
    "message": (
        "Período fora da janela coberta pelo calendário (2016-08-17 a 2027-08-17). "
        "Consulte GET /v1/calendar-info para os limites vigentes."
    ),
}

RESPONSE_KEY_NOT_FOUND = error_response(
    "Redis disponível, mas a chave não existe", KEY_NOT_FOUND_EXAMPLE
)

RESPONSE_REDIS_UNAVAILABLE = error_response(
    "Redis indisponível e cache local expirado ou ausente", SERVICE_UNAVAILABLE_EXAMPLE
)

RESPONSE_CALENDAR_UNAVAILABLE = error_response(
    "Calendário de negociação indisponível", CALENDAR_UNAVAILABLE_EXAMPLE
)

RESPONSE_RANGE_INVALID = error_response(
    "Período inválido ou fora da janela do calendário", RANGE_OUT_OF_BOUNDS_EXAMPLE
)

AUTH_NOTE = "**Autenticação**: Requer header `apikey` configurado no Kong Gateway."
