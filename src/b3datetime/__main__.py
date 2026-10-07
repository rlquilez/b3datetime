"""Entrypoint de desenvolvimento: ``PYTHONPATH=src python -m b3datetime``.

Em produção o processo é iniciado pelo uvicorn diretamente (ver o CMD do Dockerfile),
com ``--proxy-headers``. Este módulo existe para manter o código de arranque fora de
``src/b3datetime/main.py``, que é medido por coverage.
"""

from __future__ import annotations

import uvicorn

from b3datetime.main import configure_logging


def run() -> None:
    configure_logging()
    # Modo factory: não existe `app` de módulo (criá-lo no import lia o ambiente e o
    # `.env` no `import`); o uvicorn chama `create_app()` depois de iniciar.
    uvicorn.run(
        "b3datetime.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
        proxy_headers=True,
    )


if __name__ == "__main__":
    run()
