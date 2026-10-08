"""Páginas de documentação (``/docs`` e ``/redoc``) compatíveis com uma CSP estrita.

O ``get_swagger_ui_html`` do FastAPI inicializa o Swagger UI com um ``<script>`` inline, e
o ``get_redoc_html`` põe um ``<style>`` inline na página. Sob a CSP da borda —
``script-src 'self'; style-src 'self'`` —, o ``/docs`` ficou em branco e o ``/redoc``
quebrado em produção, com a suíte inteira verde (#75). Aqui nenhuma das duas páginas tem
script ou estilo inline: a inicialização do Swagger UI está em
``static/assets/swagger-init.js`` (lê a URL do contrato de ``data-openapi-url``) e o
estilo da página do ReDoc, em ``static/assets/documentacao.css``.

O que só a borda pode liberar: o ReDoc injeta estilos em tempo de execução
(styled-components), então ``/redoc`` exige ``style-src 'unsafe-inline'``. A busca do
ReDoc fica desligada (``disable-search``): ela criava um worker a partir de ``blob:``, que
``script-src 'self'`` bloqueia.

Os caminhos são relativos (``./``): o navegador os resolve contra a URL pública, com ou
sem o prefixo do Kong (ver ``OPENAPI_RELATIVE_URL`` em ``main.py``).
"""

from __future__ import annotations

from html import escape

from b3datetime.static import DOCS_CSS, FAVICON, REDOC_JS, SWAGGER_CSS, SWAGGER_INIT_JS, SWAGGER_JS

_SWAGGER = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo}</title>
<link rel="stylesheet" href="./static/{css}">
<link rel="icon" href="./static/{favicon}">
</head>
<body>
<div id="swagger-ui" data-openapi-url="{openapi}"></div>
<script src="./static/{bundle}"></script>
<script src="./static/{init}"></script>
</body>
</html>
"""

_REDOC = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo}</title>
<link rel="stylesheet" href="./static/{css}">
<link rel="icon" href="./static/{favicon}">
</head>
<body>
<noscript>O ReDoc precisa de JavaScript para exibir a documentação.</noscript>
<redoc spec-url="{openapi}" disable-search="true"></redoc>
<script src="./static/{bundle}"></script>
</body>
</html>
"""


def pagina_swagger(titulo: str, openapi_url: str) -> str:
    """HTML de ``/docs``: o Swagger UI, sem script inline."""
    return _SWAGGER.format(
        titulo=escape(titulo),
        openapi=escape(openapi_url),
        css=SWAGGER_CSS,
        favicon=FAVICON,
        bundle=SWAGGER_JS,
        init=SWAGGER_INIT_JS,
    )


def pagina_redoc(titulo: str, openapi_url: str) -> str:
    """HTML de ``/redoc``: o ReDoc, sem estilo inline e sem a busca (worker ``blob:``)."""
    return _REDOC.format(
        titulo=escape(titulo),
        openapi=escape(openapi_url),
        css=DOCS_CSS,
        favicon=FAVICON,
        bundle=REDOC_JS,
    )
