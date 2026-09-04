"""Endpoints de dias de negociação."""

from __future__ import annotations

import time

import httpx
import pytest
from freezegun import freeze_time

from src.config import Settings
from src.main import create_app
from src.services.redis_service import RedisService


async def test_calendar_info(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/calendar-info")
    assert r.status_code == 200
    body = r.json()
    assert body["exchange"] == "BVMF"
    assert body["coverage_start"] == "2024-01-01"
    assert body["coverage_end"] == "2024-12-31"
    assert body["first_session"] == "2024-01-02"
    assert body["last_session"] == "2024-12-31"
    assert body["max_range_days"] == 3660


@freeze_time("2024-01-15 13:30:00")
async def test_is_trading_day_em_sessao(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/is-trading-day")
    assert r.status_code == 200
    assert r.json() == {"date": "2024-01-15", "is_trading_day": True}


@freeze_time("2024-01-13 13:30:00")
async def test_is_trading_day_em_sabado(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/is-trading-day")
    assert r.status_code == 200
    assert r.json() == {"date": "2024-01-13", "is_trading_day": False}


@freeze_time("2024-02-12 13:30:00")
async def test_is_trading_day_em_feriado(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/is-trading-day")).json()["is_trading_day"] is False


@freeze_time("2010-06-15 13:30:00")
async def test_is_trading_day_fora_da_janela_nao_responde_false(
    client: httpx.AsyncClient,
) -> None:
    """Regressão: fora da janela a resposta era `false`, indistinguível de feriado."""
    r = await client.get("/v1/is-trading-day")
    assert r.status_code == 503
    assert "fora da janela" in r.json()["detail"]["message"]


async def test_trading_days(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/trading-days?start=2024-01-01&end=2024-01-10")
    assert r.status_code == 200
    assert r.json() == [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-08",
        "2024-01-09",
        "2024-01-10",
    ]


async def test_trading_days_exclude(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/trading-days?start=2024-01-01&end=2024-01-10&exclude=true")
    assert r.status_code == 200
    # 1º feriado, 6 e 7 fim de semana.
    assert r.json() == ["2024-01-01", "2024-01-06", "2024-01-07"]


async def test_periodo_fora_da_janela_e_400(client: httpx.AsyncClient) -> None:
    """Regressão: devolvia `[]` com HTTP 200, afirmando que a B3 não operou em 2010."""
    r = await client.get("/v1/trading-days?start=2010-01-01&end=2010-12-31")
    assert r.status_code == 400
    mensagem = r.json()["detail"]["message"]
    assert "fora da janela" in mensagem
    # A mensagem cita os limites reais, e a constante antiga não reaparece.
    assert "2024-01-01" in mensagem
    assert "2006" not in mensagem


async def test_periodo_fora_da_janela_com_exclude_e_400(client: httpx.AsyncClient) -> None:
    """Regressão: o pior caminho — devolvia todos os 365 dias como "sem negociação",
    com HTTP 200, num payload que parecia perfeitamente plausível."""
    r = await client.get("/v1/trading-days?start=2010-01-01&end=2010-12-31&exclude=true")
    assert r.status_code == 400
    assert r.json() != []


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2023-12-01", "2024-03-01"),  # começa antes da janela
        ("2024-12-01", "2025-03-01"),  # termina depois da janela
    ],
)
async def test_periodo_parcialmente_coberto_e_400(
    client: httpx.AsyncClient, start: str, end: str
) -> None:
    r = await client.get(f"/v1/trading-days?start={start}&end={end}")
    assert r.status_code == 400


async def test_end_antes_de_start_e_400(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/trading-days?start=2024-03-01&end=2024-02-01")
    assert r.status_code == 400
    assert "maior ou igual" in r.json()["detail"]["message"]


async def test_span_acima_do_limite_e_400_imediato(client: httpx.AsyncClient) -> None:
    """Regressão: `?start=2006-01-01&end=9999-12-31&exclude=true` consumia ~77 s de
    CPU, ~117 MB e devolvia ~38 MB — congelando o worker inteiro."""
    t0 = time.perf_counter()
    r = await client.get("/v1/trading-days?start=2006-01-01&end=9999-12-31&exclude=true")
    decorrido = time.perf_counter() - t0

    assert r.status_code == 400
    assert "excede o máximo" in r.json()["detail"]["message"]
    assert decorrido < 1.0, f"levou {decorrido:.2f}s; deveria ser rejeitado de imediato"


@pytest.mark.parametrize("valor", ["2024-1-1", "2024-13-45", "abc", "01/01/2024", ""])
async def test_data_invalida_e_422(client: httpx.AsyncClient, valor: str) -> None:
    """A convenção do FastAPI para erro de validação é 422; antes era 400 custom, e o
    regex aceitava datas impossíveis como 2024-13-45."""
    r = await client.get(f"/v1/trading-days?start={valor}&end=2024-12-31")
    assert r.status_code == 422


async def test_parametros_obrigatorios(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/trading-days")).status_code == 422
    assert (await client.get("/v1/trading-days?start=2024-01-01")).status_code == 422


async def test_start_igual_end_em_sessao(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/trading-days?start=2024-01-15&end=2024-01-15")
    assert r.json() == ["2024-01-15"]


async def test_start_igual_end_fora_de_sessao(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/trading-days?start=2024-01-13&end=2024-01-13")
    assert r.json() == []


async def test_503_sem_calendario(
    settings: Settings, redis_service: RedisService, make_client: object
) -> None:
    """O app serve tráfego sem calendário; só os endpoints de data degradam."""
    app = create_app(settings)
    app.state.redis_service = redis_service
    app.state.calendar = None

    async with make_client(app) as c:  # type: ignore[operator]
        for path in [
            "/v1/trading-days?start=2024-01-01&end=2024-01-10",
            "/v1/is-trading-day",
            "/v1/calendar-info",
        ]:
            r = await c.get(path)
            assert r.status_code == 503, path
            assert "Calendário" in r.json()["detail"]["message"]
        # E o restante da API continua de pé.
        assert (await c.get("/v1/hours")).status_code == 200


async def test_calendar_info_com_calendario_vazio(
    settings: Settings, redis_service: RedisService, make_client: object
) -> None:
    from tests.factories import make_empty_calendar

    app = create_app(settings)
    app.state.redis_service = redis_service
    app.state.calendar = make_empty_calendar()

    async with make_client(app) as c:  # type: ignore[operator]
        r = await c.get("/v1/calendar-info")
    assert r.status_code == 503
    assert "vazio" in r.json()["detail"]["message"]
