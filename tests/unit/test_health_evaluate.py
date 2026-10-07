"""Tabela-verdade completa do estado geral do ``/v1/health``.

O estado decide o código HTTP (``unhealthy`` → 503) e, portanto, o que orquestradores e o
``HEALTHCHECK`` da imagem fazem. As 64 combinações de entrada são todas exercitadas contra
a regra escrita em português, não contra uma cópia do código.
"""

from __future__ import annotations

from itertools import product

import pytest

from b3datetime.routers.health import (
    STATUS_DEGRADED,
    STATUS_HEALTHY,
    STATUS_UNHEALTHY,
    _evaluate,
)

IDADES = (None, 0.0)  # 0.0 é idade legítima: "cache recém-preenchido", não "ausente"
BOOLS = (False, True)


def _esperado(
    calendario: bool,
    conectado: bool,
    idade_open: float | None,
    idade_close: float | None,
    expirado_open: bool,
    expirado_close: bool,
) -> str:
    # Regra: sem calendário, metade da API não responde → unhealthy. Com Redis, healthy.
    # Sem Redis, só é degradado se as DUAS chaves têm cache presente e não expirado.
    if not calendario:
        return STATUS_UNHEALTHY
    if conectado:
        return STATUS_HEALTHY
    cache_serve = (
        idade_open is not None and idade_close is not None and not (expirado_open or expirado_close)
    )
    return STATUS_DEGRADED if cache_serve else STATUS_UNHEALTHY


@pytest.mark.parametrize(
    ("calendario", "conectado", "idade_open", "idade_close", "expirado_open", "expirado_close"),
    list(product(BOOLS, BOOLS, IDADES, IDADES, BOOLS, BOOLS)),
)
def test_estado_geral(
    calendario: bool,
    conectado: bool,
    idade_open: float | None,
    idade_close: float | None,
    expirado_open: bool,
    expirado_close: bool,
) -> None:
    cache = {
        "redis_connected": conectado,
        "open_cache_age_seconds": idade_open,
        "close_cache_age_seconds": idade_close,
        "open_cache_expired": expirado_open,
        "close_cache_expired": expirado_close,
    }
    assert _evaluate(cache, calendario) == _esperado(
        calendario, conectado, idade_open, idade_close, expirado_open, expirado_close
    )


def test_idade_zero_conta_como_cache_presente() -> None:
    """Regressão: ``0.0`` era lido como ausente e um cache fresco virava unhealthy."""
    cache = {
        "redis_connected": False,
        "open_cache_age_seconds": 0.0,
        "close_cache_age_seconds": 0.0,
        "open_cache_expired": False,
        "close_cache_expired": False,
    }
    assert _evaluate(cache, calendar_available=True) == STATUS_DEGRADED
