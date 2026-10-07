"""Wiring real da aplicação: lifespan, falhas de dependência no arranque e import sem I/O.

Estes testes executam o lifespan de verdade — constroem o calendário BVMF real e tentam
o Redis de ``localhost`` —, por isso vivem na integração e não no bloco de componente.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

import b3datetime.main as main_mod
from b3datetime.config import Settings
from b3datetime.main import create_app
from b3datetime.services.calendar_service import CalendarUnavailableError
from b3datetime.services.redis_service import RedisService

pytestmark = pytest.mark.integration

# Layout src: o subprocesso precisa do diretório do pacote no sys.path.
SRC_DIR = Path(__file__).resolve().parents[2] / "src"


async def test_lifespan_popula_o_estado(lifespan_app: FastAPI) -> None:
    assert lifespan_app.state.redis_service is not None
    assert lifespan_app.state.calendar is not None


async def test_app_sobe_com_calendario_quebrado(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, make_client: object
) -> None:
    """Regressão: a falha do calendário levantava RuntimeError em tempo de import,
    antes de o uvicorn abrir a porta — sem health endpoint e em crash-loop."""

    def boom(*_a: object, **_k: object) -> None:
        raise CalendarUnavailableError("catálogo indisponível")

    monkeypatch.setattr(main_mod, "build_bvmf_calendar", boom)

    app = create_app(settings)
    async with LifespanManager(app, startup_timeout=60):
        assert app.state.calendar is None
        async with make_client(app) as c:  # type: ignore[operator]
            # A API segue de pé, e o health torna a falha visível.
            assert (await c.get("/v1/health")).status_code == 503
            assert (await c.get("/")).status_code == 200


async def test_app_sobe_com_redis_fora(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    async def falha(_self: RedisService) -> None:
        return None

    monkeypatch.setattr(RedisService, "connect", falha)
    app = create_app(settings)
    async with LifespanManager(app, startup_timeout=180):
        assert app.state.redis_service is not None


@pytest.mark.slow
def test_import_nao_faz_io() -> None:
    """Regressão: o import conectava no Redis e construía dez anos de calendário.

    Rodado em subprocesso, com o Redis apontando para uma porta fechada: é a única
    verificação real de que nenhum I/O voltou para o tempo de import.
    """
    codigo = textwrap.dedent("""
        import time
        t = time.time()
        import b3datetime.main
        assert b3datetime.main.app is not None
        elapsed = time.time() - t
        assert elapsed < 3, f"import levou {elapsed:.2f}s; parece haver I/O"
    """)
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", codigo],
        env={
            "REDIS_URL_ENV": "redis://127.0.0.1:1",
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(SRC_DIR),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
