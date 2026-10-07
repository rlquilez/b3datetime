"""Contrato do schema OpenAPI, derivado das rotas da própria app.

O conjunto de rotas vem de ``app.routes`` — e não de uma lista escrita à mão — para que
um router novo não possa ficar fora da documentação sem que um teste perceba.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from b3datetime.config import Settings
from b3datetime.routers.openapi_examples import (
    API_KEY_HEADER,
    API_KEY_SCHEME,
    OPENAPI_TAGS,
    TAG_DATES,
    TAG_HEALTH,
    TAG_HOURS,
    TAG_ROOT,
)
from b3datetime.services.calendar_service import TradingCalendar
from b3datetime.services.redis_service import RedisService
from scripts.gerar_openapi import SNAPSHOT, contrato_servido, serializar
from tests.conftest import build_app

HOURS_CODES = {"200", "404", "502", "503"}
DOCUMENTED_CODES: dict[str, set[str]] = {
    "/": {"200"},
    "/v1/hours": HOURS_CODES,
    "/v1/hours/open": HOURS_CODES,
    "/v1/hours/close": HOURS_CODES,
    "/v1/health": {"200", "503"},
    "/v1/is-trading-day": {"200", "503"},
    "/v1/calendar-info": {"200", "503"},
    "/v1/trading-days": {"200", "400", "422", "503"},
}


def _api_routes(routes: Iterable[Any]) -> Iterator[APIRoute]:
    """Achata `app.routes`: o FastAPI >= 0.141 expõe routers incluídos como _IncludedRouter."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        else:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                yield from _api_routes(inner.routes)


def _public_routes(app: FastAPI) -> set[str]:
    return {r.path for r in _api_routes(app.routes) if r.include_in_schema}


async def _schema(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    return dict(r.json())


async def test_todas_as_rotas_publicas_estao_no_schema(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    schema = await _schema(client)
    assert set(schema["paths"]) == _public_routes(app)
    # Uma rota nova também precisa entrar na tabela de códigos documentados.
    assert set(DOCUMENTED_CODES) == _public_routes(app)


@pytest.mark.parametrize(("path", "codes"), sorted(DOCUMENTED_CODES.items()))
async def test_codigos_documentados_por_operacao(
    client: httpx.AsyncClient, path: str, codes: set[str]
) -> None:
    schema = await _schema(client)
    assert set(schema["paths"][path]["get"]["responses"]) == codes


async def test_info(client: httpx.AsyncClient, settings: Settings) -> None:
    schema = await _schema(client)
    info = schema["info"]
    assert info["title"] == settings.api_title
    assert info["version"] == settings.api_version
    assert info["license"]["name"] == "MIT"
    assert "github.com/rlquilez/b3datetime" in info["contact"]["url"]
    assert "github.com/rlquilez/b3datetime" in schema["externalDocs"]["url"]


async def test_tags_declaradas_ordenadas_e_usadas(client: httpx.AsyncClient) -> None:
    schema = await _schema(client)
    assert [t["name"] for t in schema["tags"]] == [TAG_HOURS, TAG_DATES, TAG_HEALTH, TAG_ROOT]
    assert all(t["description"] for t in schema["tags"])
    used = {tag for path in schema["paths"].values() for op in path.values() for tag in op["tags"]}
    assert used == {t["name"] for t in OPENAPI_TAGS}


async def test_sem_autenticacao_por_padrao(client: httpx.AsyncClient) -> None:
    """Não há autenticação no momento: o schema não pode prometer um header que o
    gateway não exige, e a descrição precisa dizer isso."""
    schema = await _schema(client)
    assert "securitySchemes" not in schema.get("components", {})
    assert "security" not in schema
    assert "Sem autenticação no momento" in schema["info"]["description"]
    assert (await client.get("/")).json()["authentication"] == {
        "required": False,
        "type": None,
        "header": None,
        "managed_by": "Kong Gateway",
    }


async def test_esquema_apikey_quando_exigido(
    settings: Settings, redis_service: RedisService, test_calendar: TradingCalendar
) -> None:
    """Com API_KEY_REQUIRED=true o schema declara ApiKeyAuth como requisito global — só
    metadado: a app continua sem código de autenticação."""
    app = build_app(
        settings.model_copy(update={"api_key_required": True}), redis_service, test_calendar
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        schema = await _schema(c)
        root = (await c.get("/")).json()

    scheme = schema["components"]["securitySchemes"][API_KEY_SCHEME]
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == API_KEY_HEADER
    assert schema["security"] == [{API_KEY_SCHEME: []}]
    assert "Authorize" in schema["info"]["description"]
    assert root["authentication"] == {
        "required": True,
        "type": "API Key",
        "header": API_KEY_HEADER,
        "managed_by": "Kong Gateway",
    }


async def test_503_do_health_documenta_o_schema(client: httpx.AsyncClient) -> None:
    """O corpo do 503 é o mesmo HealthResponse do 200; sem `model`, o schema não era
    documentado e o cliente só tinha um exemplo (#46)."""
    content = (await _schema(client))["paths"]["/v1/health"]["get"]["responses"]["503"]["content"]
    assert content["application/json"]["schema"] == {"$ref": "#/components/schemas/HealthResponse"}


async def test_exemplos_do_health_sao_combinacoes_possiveis(client: httpx.AsyncClient) -> None:
    """Com o calendário disponível os limites sempre vêm; sem ele, só `available`. O
    exemplo `unhealthy` antigo mostrava `{"available": true}` sem limites (#46)."""
    responses = (await _schema(client))["paths"]["/v1/health"]["get"]["responses"]
    completo = {"available", "first_session", "last_session", "sessions_count"}
    for code in ("200", "503"):
        for nome, exemplo in responses[code]["content"]["application/json"]["examples"].items():
            calendario = exemplo["value"]["calendar"]
            esperado = completo if calendario["available"] else {"available"}
            assert set(calendario) == esperado, f"{code}/{nome}"


async def test_schemas_tipados(client: httpx.AsyncClient) -> None:
    """`cache` e `calendar` do health e o corpo de `GET /` eram dicts opacos."""
    components = (await _schema(client))["components"]["schemas"]
    for name in [
        "CacheStatus",
        "CalendarStatus",
        "HealthResponse",
        "RootResponse",
        "CalendarInfoResponse",
        "TradingHours",
        "TradingTime",
        "TradingDayResponse",
    ]:
        assert name in components, name
    for prop, spec in components["CalendarInfoResponse"]["properties"].items():
        assert spec.get("description"), f"{prop} sem description"


async def test_snapshot_do_contrato_esta_em_dia() -> None:
    """``tests/contract/openapi.json`` é o contrato servido, byte a byte.

    Toda mudança de contrato aparece no diff do commit, e o job ``Contrato · oasdiff``
    compara este arquivo com o da última release para barrar breaking change sem MAJOR.
    Divergiu? ``PYTHONPATH=src python scripts/gerar_openapi.py`` e revise o diff.
    """
    atual = serializar(await contrato_servido())
    assert SNAPSHOT.read_text(encoding="utf-8") == atual, (
        "snapshot do contrato desatualizado: rode `PYTHONPATH=src python scripts/gerar_openapi.py`"
    )
