# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não publicado]

### Adicionado

- Fluxo obrigatório de trabalho documentado no `CLAUDE.md` e skill `release` em `.claude/skills/release/SKILL.md`, definindo a convenção SemVer + Keep a Changelog. (#1)
- Infraestrutura de projeto: `pyproject.toml` (ruff, mypy, pytest, coverage, bandit), `requirements-dev.txt`, `LICENSE` MIT, `.dockerignore` e `.github/dependabot.yml`. (#2)

### Corrigido

- `.gitignore` ignorava `.DS_Store/` com barra final, padrão que casa apenas com diretórios — os arquivos `.DS_Store` continuavam rastreados. (#2)

### Segurança

- `pandas` passa a ser declarado e pinado no `requirements.txt`. Era dependência direta de `src/routers/dates.py` mas resolvia apenas de forma transitiva por `exchange-calendars`, que **não declara constraint de versão** — cada rebuild da imagem instalava uma versão arbitrária. (#2)

## [1.0.0] - 2026-03-12

Primeira versão da API, desenvolvida entre 2025-12-26 e 2026-03-12.

### Adicionado

- `GET /v1/hours`, `GET /v1/hours/open` e `GET /v1/hours/close` — horários de abertura e fechamento da B3, lidos do Redis com cache local de 1 hora como fallback.
- `GET /v1/is-trading-day` — verifica se o dia atual é dia de negociação, usando o calendário BVMF do `exchange_calendars`.
- `GET /v1/trading-days` — lista dias de negociação ou de não-negociação num período, com o parâmetro `exclude`.
- `GET /v1/health` — estado da API e do Redis, com idade do cache local.
- `GET /` — metadados da API, endpoints disponíveis e forma de autenticação.
- Documentação OpenAPI em `/docs` (Swagger UI) e `/redoc`.
- Suporte a proxy reverso via a variável de ambiente `ROOT_PATH`, com `openapi.json` referenciado por caminho relativo para funcionar atrás do Kong Gateway.
- Imagem Docker multi-arquitetura (`linux/amd64`, `linux/arm64`) publicada por GitHub Actions.
- Timezone `America/Sao_Paulo` em todas as operações de data e hora.

[Não publicado]: https://github.com/rlquilez/b3datetime/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rlquilez/b3datetime/releases/tag/v1.0.0
