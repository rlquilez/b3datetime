// Inicialização do Swagger UI de /docs, fora do HTML (src/b3datetime/documentacao.py).
// Inline, como o get_swagger_ui_html do FastAPI a gera, ela é bloqueada por uma CSP sem
// 'unsafe-inline' e a página fica em branco — foi o que aconteceu em produção (#75).
// A URL do contrato vem do atributo data-openapi-url, relativa à página.
(function () {
  "use strict";
  var alvo = document.getElementById("swagger-ui");
  window.ui = SwaggerUIBundle({
    url: alvo.getAttribute("data-openapi-url"),
    dom_id: "#swagger-ui",
    layout: "BaseLayout",
    deepLinking: true,
    showExtensions: true,
    showCommonExtensions: true,
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
  });
})();
