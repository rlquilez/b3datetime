"""Assets estáticos da documentação, servidos localmente.

Antes, `/redoc` carregava `cdn.redoc.ly/redoc/latest/...` — origem de terceiro, versão
não fixada e sem SRI — apesar do docstring afirmar "without CDN", e `/docs` caía no
`cdn.jsdelivr.net` default do FastAPI. Além do risco de supply chain, as duas páginas
renderizavam em branco em rede sem egress, atrás de proxy corporativo ou sob CSP.

Os arquivos são versionados no repositório e copiados para a imagem junto com `src/`.
Para atualizar, baixe a nova versão, ajuste as constantes abaixo e valide as páginas.
"""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent

SWAGGER_UI_VERSION = "5.17.14"
REDOC_VERSION = "2.1.5"

SWAGGER_JS = "swagger-ui-bundle.js"
SWAGGER_CSS = "swagger-ui.css"
REDOC_JS = "redoc.standalone.js"
FAVICON = "favicon.png"

__all__ = [
    "FAVICON",
    "REDOC_JS",
    "REDOC_VERSION",
    "STATIC_DIR",
    "SWAGGER_CSS",
    "SWAGGER_JS",
    "SWAGGER_UI_VERSION",
]
