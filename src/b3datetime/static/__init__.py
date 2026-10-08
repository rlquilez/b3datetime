"""Assets estáticos da documentação, servidos localmente.

Antes, `/redoc` carregava `cdn.redoc.ly/redoc/latest/...` — origem de terceiro, versão
não fixada e sem SRI — apesar do docstring afirmar "without CDN", e `/docs` caía no
`cdn.jsdelivr.net` default do FastAPI. Além do risco de supply chain, as duas páginas
renderizavam em branco em rede sem egress, atrás de proxy corporativo ou sob CSP.

Os arquivos são versionados no repositório e copiados para a imagem junto com o pacote.
Para atualizar, baixe a nova versão, ajuste as constantes abaixo e valide as páginas.

Ficam em ``assets/``, e não na raiz do pacote: o mount apontava para o diretório do
próprio pacote e servia ``__init__.py`` (este arquivo) como ``text/x-python``.
"""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "assets"

SWAGGER_UI_VERSION = "5.33.0"
REDOC_VERSION = "2.5.4"

SWAGGER_JS = "swagger-ui-bundle.js"
SWAGGER_CSS = "swagger-ui.css"
REDOC_JS = "redoc.standalone.js"
FAVICON = "favicon.png"
# Do próprio projeto, não vendorizados: a inicialização do Swagger UI e o estilo da página
# do ReDoc, fora do HTML para as páginas funcionarem sob CSP sem 'unsafe-inline' (#75).
SWAGGER_INIT_JS = "swagger-init.js"
DOCS_CSS = "documentacao.css"

__all__ = [
    "DOCS_CSS",
    "FAVICON",
    "REDOC_JS",
    "REDOC_VERSION",
    "STATIC_DIR",
    "SWAGGER_CSS",
    "SWAGGER_INIT_JS",
    "SWAGGER_JS",
    "SWAGGER_UI_VERSION",
]
