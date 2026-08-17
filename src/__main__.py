"""Entrypoint de desenvolvimento: ``python -m src``.

Em produção o processo é iniciado pelo uvicorn diretamente (ver o CMD do Dockerfile),
com ``--proxy-headers``. Este módulo existe para manter o código de arranque fora de
``src/main.py``, que é medido por coverage.
"""

from __future__ import annotations

import uvicorn

from src.main import configure_logging


def run() -> None:
    configure_logging()
    uvicorn.run(
        "src.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
        proxy_headers=True,
    )


if __name__ == "__main__":
    run()
