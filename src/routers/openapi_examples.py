"""Metadados OpenAPI compartilhados: tags, segurança, exemplos e blocos ``responses``.

Os três routers descreviam respostas de erro com dicionários estruturalmente idênticos.
Centralizá-los evita que a métrica de duplicação do SonarQube reprove o quality gate, e
garante que o corpo de erro documentado seja o mesmo em toda a API. Pelo mesmo motivo
as tags e o esquema de segurança vivem aqui: são a única fonte para o app e para os
testes de contrato.
"""

from __future__ import annotations

from typing import Any

# --- Tags: a ordem aqui é a ordem de exibição no Swagger UI ---------------------------

TAG_HOURS = "Horários de Operação"
TAG_DATES = "Dias de Negociação"
TAG_HEALTH = "Health Check"
TAG_ROOT = "Informações da API"

OPENAPI_TAGS: list[dict[str, str]] = [
    {
        "name": TAG_HOURS,
        "description": (
            "Abertura e fechamento lidos do Redis num único `MGET`, com cache local de até "
            "1 hora como fallback."
        ),
    },
    {
        "name": TAG_DATES,
        "description": (
            "Dias de negociação segundo o calendário BVMF do `exchange_calendars`, numa "
            "janela móvel consultável em `/v1/calendar-info`."
        ),
    },
    {
        "name": TAG_HEALTH,
        "description": (
            "Estado da API e das dependências. `unhealthy` responde **503**, o que o "
            "`HEALTHCHECK` do Docker e as probes do Kubernetes detectam."
        ),
    },
    {
        "name": TAG_ROOT,
        "description": "Metadados, links (já com o prefixo do proxy) e forma de autenticação.",
    },
]

# --- Autenticação: só metadado; quem valida a chave (quando exigida) é o Kong ---------

API_KEY_SCHEME = "ApiKeyAuth"
API_KEY_HEADER = "apikey"

SECURITY_SCHEMES: dict[str, dict[str, str]] = {
    API_KEY_SCHEME: {
        "type": "apiKey",
        "in": "header",
        "name": API_KEY_HEADER,
        "description": (
            "Chave validada pelo Kong Gateway (plugin key-auth). A aplicação não valida a chave."
        ),
    }
}

AUTH_DESCRIPTION_REQUIRED = (
    "## Autenticação\n\n"
    f"Todas as requisições devem incluir o header `{API_KEY_HEADER}`, validado pelo Kong "
    'Gateway. Use **Authorize** para informá-lo no "Try it out".'
)
AUTH_DESCRIPTION_NONE = (
    "## Autenticação\n\n"
    "**Sem autenticação no momento.** As requisições não precisam de nenhum header. Quando "
    f"o Kong passar a exigir o header `{API_KEY_HEADER}`, a API é publicada com "
    "`API_KEY_REQUIRED=true` e esta documentação passa a declarar o esquema de segurança."
)


def auth_description(api_key_required: bool) -> str:
    """Seção de autenticação da descrição da API, coerente com ``API_KEY_REQUIRED``."""
    return AUTH_DESCRIPTION_REQUIRED if api_key_required else AUTH_DESCRIPTION_NONE


# --- Blocos `responses` ---------------------------------------------------------------


def error_response(description: str, example: dict[str, Any]) -> dict[str, Any]:
    """Monta uma entrada de `responses` com um único exemplo de erro."""
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


def success_response(description: str, example: dict[str, Any] | list[Any]) -> dict[str, Any]:
    """Monta uma entrada de sucesso de `responses` com um único exemplo."""
    return {
        "description": description,
        "content": {"application/json": {"example": example}},
    }


# Reutilizada pelo handler de 502 em src/main.py: o que a documentação promete é o que
# a API responde.
BAD_GATEWAY_MESSAGE = "O valor armazenado no Redis não está no formato esperado"

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

INVALID_UPSTREAM_EXAMPLE = {"error": "Bad Gateway", "message": BAD_GATEWAY_MESSAGE}

CALENDAR_UNAVAILABLE_EXAMPLE = {
    "error": "Service Unavailable",
    "message": "Calendário de negociação indisponível",
}

RANGE_OUT_OF_BOUNDS_EXAMPLE = {
    "error": "Bad Request",
    "message": (
        "Período fora da janela coberta pelo calendário (2016-09-04 a 2027-09-03). "
        "Consulte GET /v1/calendar-info para os limites vigentes."
    ),
}

CALENDAR_INFO_EXAMPLE = {
    "exchange": "BVMF",
    "coverage_start": "2016-09-04",
    "coverage_end": "2027-09-03",
    "first_session": "2016-09-05",
    "last_session": "2027-09-03",
    "sessions_count": 2730,
    "max_range_days": 3660,
}

RESPONSE_KEY_NOT_FOUND = error_response(
    "Redis disponível, mas a chave não existe", KEY_NOT_FOUND_EXAMPLE
)

RESPONSE_REDIS_UNAVAILABLE = error_response(
    "Redis indisponível e cache local expirado ou ausente", SERVICE_UNAVAILABLE_EXAMPLE
)

RESPONSE_INVALID_UPSTREAM = error_response(
    "Valor lido do Redis fora do formato HH:MM", INVALID_UPSTREAM_EXAMPLE
)

RESPONSE_CALENDAR_UNAVAILABLE = error_response(
    "Calendário de negociação indisponível", CALENDAR_UNAVAILABLE_EXAMPLE
)

RESPONSE_RANGE_INVALID = error_response(
    "Período inválido ou fora da janela do calendário", RANGE_OUT_OF_BOUNDS_EXAMPLE
)

# Os três endpoints de horários compartilham exatamente os mesmos erros.
RESPONSES_HOURS_ERRORS: dict[int | str, dict[str, Any]] = {
    404: RESPONSE_KEY_NOT_FOUND,
    502: RESPONSE_INVALID_UPSTREAM,
    503: RESPONSE_REDIS_UNAVAILABLE,
}
