# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não publicado]

## [2.1.0] - 2026-10-07

### Adicionado

- `GET /` informa em `build` o commit (SHA) da imagem em execução. A versão só muda nas releases; o `build` muda a cada deploy, e é por ele que o pipeline confirma que a produção já serve a imagem recém-publicada. Fora da imagem publicada, o valor é `local`. (#66)
- **Stack de testes completa, com cada bloco visível no pipeline** (#51–#73). Nenhuma imagem é publicada sem todos os blocos aprovados. Os blocos novos:
  - **property-based** (Hypothesis) e fuzzing da API inteira pelo próprio contrato (Schemathesis);
  - **teste de mutação** bloqueante (mutmut, 99,59%);
  - **arquitetura** como contrato (import-linter, import sem I/O, convenções verificadas na AST);
  - **código morto** (vulture, deptry, fixtures órfãs);
  - **contrato evolutivo** (oasdiff: breaking change só com bump de MAJOR);
  - **DAST** com OWASP ZAP contra a imagem;
  - **carga** com k6;
  - SAST também dos próprios workflows (CodeQL `actions`, zizmor);
  - **verificação pós-deploy** em produção: o `build` publicado, o E2E de leitura, uma varredura passiva e os headers de segurança da borda.

  A arquitetura completa, com racional e diagramas, está em `tests/README.md`.
- Os parâmetros `start` e `end` de `/v1/trading-days` ganham exemplo no OpenAPI: o período de 2026-09-01 a 2026-09-07, cuja resposta é exatamente a dos dois exemplos de `200` (com e sem `exclude`). O *Try it out* do `/docs` já vem preenchido com um período válido. (#69)

### Alterado

- O código passa a seguir o layout `src/` padrão do Python: o pacote se chama `b3datetime` (`src/b3datetime/`). (#52)
- A aplicação é iniciada em modo *factory* — `uvicorn b3datetime.main:create_app --factory` — e não existe mais um `app` de módulo: criá-lo no `import` lia o ambiente e o `.env` (e um `TIMEZONE` inválido derrubava o import antes de qualquer log). Só afeta quem sobrescreve o comando do container; o `CMD` da imagem já usa o comando novo. (#60)

### Corrigido

- `/v1/hours`, `/v1/hours/open` e `/v1/hours/close` deixam de servir como `200` um horário com dígitos não-ASCII vindo do Redis (ex.: `1٠:00`, com o zero arábico-índico): o padrão `HH:MM` do contrato publicado sempre foi ASCII, e agora a validação também. A resposta é o `502` documentado para valor inválido. O texto do `pattern` no OpenAPI passa de `\d` para `[0-9]`, com o mesmo significado. (#59)
- Um valor no Redis que não é UTF-8 deixa de produzir `500`: é um valor inválido do upstream e responde o `502` documentado. (#59)
- O `502` ("valor inválido no Redis") deixa de ser usado para erros internos de validação, que agora são `500`. (#59)
- A idade do cache local (que decide entre servir o cache e responder `503`) e o intervalo de reconexão ao Redis passam a ser medidos em tempo real. Com um `TIMEZONE` que tem horário de verão, a volta do relógio fazia 2 h reais contarem como 1 h: um cache vencido seguia sendo servido e a reconexão demorava mais do que o configurado. (#61)

### Segurança

- **Swagger UI (`/docs`) atualizado de 5.17.14 para 5.33.0.** A versão anterior embutia o DOMPurify 3.1.4, com 19 CVEs de XSS conhecidos (entre eles CVE-2025-26791); a nova traz o DOMPurify 3.4.13. O ReDoc (`/redoc`) também foi atualizado, de 2.1.5 para 2.5.4. A vulnerabilidade foi encontrada pelo novo teste dinâmico de segurança (DAST, OWASP ZAP), o único scanner que enxerga esses assets servidos localmente. (#69)
- A URL do Redis deixa de vazar credenciais no log em formas que a redação não cobria: sem host (`redis://:senha@/0`, `unix://:senha@/caminho.sock`) e com a senha na query (`?password=`). Uma porta inválida em `REDIS_URL_ENV` (`:abc`, `:99999`) também deixa de derrubar o arranque. (#58)

## [2.0.4] - 2026-09-26

### Adicionado

- **Teste E2E no pipeline, cobrindo 100% dos endpoints publicados** contra a imagem real, com Redis real e o calendário BVMF real, em quatro ambientes: principal, sem Redis, sem calendário e Redis que sobe depois. Toda resposta documentada de toda operação é exercitada e validada contra o `/openapi.json` servido, e um teste exige cobertura igual ao contrato (hoje, 8 operações e 23 respostas). Também são validadas as consultas (feriados da B3, complemento do `exclude`, contagens e concordância entre endpoints), a documentação e a recuperação sem restart quando o Redis volta. A mesma suíte roda contra a produção só com o que lê (`E2E_BASE_URL`). Nenhuma imagem é publicada sem ela. (#47)

### Alterado

- **Python 3.14 passa a ser a única versão suportada e testada** (`requires-python = ">=3.14"`, alvo do ruff e do mypy): é o runtime da imagem, e nenhum ambiente usa outra. O CI deixa de rodar a suíte também em 3.11. (#45)

### Corrigido

- `GET /v1/health` informava em `calendar.first_session` o **início da janela** do calendário, e não a primeira sessão. Quando a janela começa num fim de semana ou feriado — em produção, a partir de 01/10/2026 —, o health anunciava como primeiro pregão um dia sem pregão e discordava de `GET /v1/calendar-info`. Agora os dois concordam sempre. (#46)
- O `503` de `GET /v1/health` passa a documentar o schema da resposta (o mesmo `HealthResponse` do `200`). O exemplo `unhealthy` foi trocado por dois exemplos que a API de fato produz: Redis fora sem cache, e calendário indisponível. (#46)

## [2.0.3] - 2026-09-26

### Alterado

- Imagem base trocada de `python:3.14-slim` (Debian) para a **`python:3.14-alpine` oficial**, fixada por digest nos dois estágios. O Dependabot propõe os digests novos da mesma tag, e a troca de minor ou major do Python fica de fora de propósito. O container continua rodando como `app` (uid 1001), com a mesma porta, o mesmo `HEALTHCHECK` e o mesmo comando; o runtime cai para 30 pacotes do sistema. (#39)
- CI: a imagem publicada reaproveita exatamente a camada amd64 que foi escaneada, e o cache do build ganha escopos separados para verificação e publicação. Com isso o arm64 deixa de ser reconstruído do zero a cada publicação. (#39)
- Dependências atualizadas: `pydantic` 2.13.4 → 2.13.5, `starlette` 1.6.0 → 1.7.0, `uvicorn` 0.52.4 → 0.54.0 e `pandas` 3.0.5 → 3.0.6. Nas de desenvolvimento: `coverage` 7.15.4 → 7.16.1, `pytest-randomly` 4.1.0 → 5.0.0, `fakeredis` 2.37.1 → 2.38.0 e `ruff` 0.16.5 → 0.16.9. Com o `starlette` 1.7, as respostas CORS passam a incluir `Vary: Origin`. (#40)
- **Release automática.** O commit de release na `main` basta: depois da publicação, o job `release` do CI cria a tag `vX.Y.Z` nesse commit, adiciona `X`, `X.Y` e `X.Y.Z` à imagem que acabou de ser publicada (pelo digest, sem rebuild) e publica a Release com a seção do CHANGELOG. Acabam a tag manual e a regra de só enviá-la depois de o CI publicar a imagem. (#41)
- Re-executar um run antigo do CI não republica mais a imagem por cima da `main` atual; como a produção puxa `latest` sozinha, isso reverteria a produção. (#41)

### Removido

- `.github/workflows/release.yml`, absorvido pelo job `release` do `ci.yml`. As checagens de versão que ele fazia na tag já rodavam nos testes, antes de qualquer publicação. (#41)

### Segurança

- Os 173 alertas do Trivy no code scanning deixam de existir, e o Trivy passa a reportar 0 vulnerabilidades na imagem. Todos estavam em pacotes do Debian herdados da imagem base (perl, util-linux, glibc, systemd, pam, ncurses, tar...), 150 deles sem correção disponível, e a imagem Alpine não tem esses pacotes. (#39)
- A camada de patches do sistema (`apk upgrade`) é refeita a cada execução do CI. Com a base Debian, o `apt-get upgrade` equivalente vinha do cache do build enquanto o digest da base não mudava. As correções publicadas depois de 04/09 (perl-base CRITICAL, gzip, pcre2, sqlite) nunca entraram na imagem, e a `latest` em produção as carregava. (#39)

## [2.0.2] - 2026-09-04

### Alterado

- Runtime da imagem migrado para **Python 3.14** (`python:3.14-slim`). A suíte continua rodando em 3.11 (mínimo suportado) e agora também em 3.14 no CI, e `sonar.python.version` acompanha o runtime. A remoção de `pip`/`setuptools`/`wheel` da imagem passa a descobrir o `site-packages` via `sysconfig`, em vez de um caminho com a versão hardcoded. (#31)
- Dependências atualizadas: `exchange-calendars` 4.5.6 → 4.13.2, `uvicorn` 0.52.3 → 0.52.4, `fakeredis` 2.37.0 → 2.37.1, `ruff` 0.16.3 → 0.16.5. (#29)
- Todas as actions dos workflows nos majors com runtime Node 24 (`checkout@v7`, `setup-python@v7`, `upload-artifact@v7`, `download-artifact@v8`, `dependency-review-action@v5`, `gitleaks-action@v3`, `docker/*`, `action-gh-release@v3`, `setup-crane@v0.7`), eliminando as anotações de descontinuação do Node 20. (#30)

## [2.0.1] - 2026-09-04

### Adicionado

- `API_KEY_REQUIRED` (padrão `false`): quando `true`, o OpenAPI declara o esquema de segurança `ApiKeyAuth` (header `apikey`) como requisito global, o Swagger UI exibe **Authorize** e `GET /` informa `authentication.required: true`. É só metadado — a validação continua no Kong e a aplicação não autentica nada. (#24)
- Tags com descrição e ordem fixa, `502` documentado em `/v1/hours*`, exemplo de resposta em `GET /v1/calendar-info`, descrição em todos os campos, tabela de códigos de resposta na descrição da API, link para o README em `externalDocs` e schemas nomeados para `cache` e `calendar` de `/v1/health` e para `GET /`. O JSON das respostas não muda. (#24)
- Suíte de testes cobre todos os endpoints e páginas nos três modos de proxy (sem proxy, Kong com `strip_path` `true` e `false`), os erros 404/502/503 nos três endpoints de horários, o 503 de `/v1/calendar-info` sem calendário, o preflight CORS, os assets estáticos (content-type, `HEAD`, traversal, arquivos do pacote) e a sincronia da versão entre `src/config.py`, `pyproject.toml`, README e CHANGELOG. (#25)
- Smoke test da imagem no CI (`scripts/smoke_image.sh`, também executável localmente): container real sem Redis e, depois, com Redis real e `ROOT_PATH`, verificando todas as páginas, assets e endpoints nas duas formas em que o Kong entrega o caminho, barra final, casos negativos e o `HEALTHCHECK` do Docker. Tripwires no pipeline para testes pulados e relatórios ausentes; SonarQube pulado em PRs do Dependabot (que não recebem secrets) e `dependency-review` incluído no agregador `ci-ok`. (#27)

### Alterado

- URLs com barra final (`/docs/`, `/v1/hours/`) respondem `404` em vez de `307`. O redirecionamento era montado com o header `Host` recebido do proxy e, atrás do Kong com `preserve_host: false`, apontava para o endereço interno do upstream sem o prefixo — destino inalcançável que ainda expunha IP e porta internos. Nenhuma URL documentada tem barra final. (#23)
- Os links de `GET /` incluem o prefixo do proxy (`/<prefixo>/docs`, `/<prefixo>/v1/hours`, ...) e `docs.openapi` deixa de ser relativo: resolvido contra `/<prefixo>` por um cliente, `./openapi.json` caía em `/openapi.json`, fora do prefixo. (#24)
- `GET /` e a documentação deixam de afirmar que o header `apikey` é obrigatório: `authentication` ganha o campo `required` e hoje informa `false`, porque não há autenticação em vigor. (#24)

### Corrigido

- A documentação (OpenAPI, `GET /` e README) afirmava uma autenticação por `apikey` que não existe no momento. (#24)
- `/docs` e `/redoc` ficavam em branco atrás do Kong com `strip_path: true`: a página carregava, mas `/<prefixo>/static/*` respondia `404`. O Kong removia o prefixo de `path` enquanto `ROOT_PATH` o mantinha em `root_path`, violando o contrato ASGI de que `path` começa com `root_path`; o `Mount("/static")` propagava então um `root_path` que o `StaticFiles` não conseguia remover e procurava `static/<arquivo>` dentro do diretório de assets. Um middleware recompõe o prefixo, e as duas configurações do Kong (`strip_path` `true` e `false`) passam a funcionar. (#23)
- A documentação afirmava que `strip_path: false` fazia tudo responder `404`; com o Starlette 1.x era o oposto. (#23)

### Segurança

- Redirecionamentos não expõem mais host e porta internos do upstream no header `Location`. (#23)
- `/static` deixa de servir arquivos do pacote Python (`/static/__init__.py` respondia `200 text/x-python`): os assets passam a viver em `src/static/assets/`. (#23)

## [2.0.0] - 2026-08-17

Esta versão corrige respostas que antes eram **silenciosamente erradas**. As mudanças de
código de status são a razão do incremento MAJOR: mesmo onde o comportamento anterior
estava errado, clientes e orquestradores reagem ao status. Veja o guia de migração no
[README](README.md#-migração-da-v1-para-a-v2).

### Adicionado

- `GET /v1/calendar-info`, expondo `coverage_start`, `coverage_end`, `first_session`, `last_session`, `sessions_count` e `max_range_days`. (#6)
- Suíte de testes com 136 casos e 99,8% de coverage, incluindo um teste de regressão nomeado por defeito corrigido. (#8)
- Pipeline de CI com lint (ruff), tipagem (mypy), testes em Python 3.11 e 3.12, SAST (bandit, CodeQL), CVEs em dependências (pip-audit), varredura de segredos (gitleaks), scan de imagem e filesystem (Trivy), SBOM e quality gate bloqueante do SonarQube. (#9)
- Workflow de release disparado por tag, que valida a consistência da versão e retagueia a imagem com o semver sem rebuild. (#11)
- Variáveis de configuração `MAX_RANGE_DAYS`, `CALENDAR_START_OFFSET_YEARS`, `REDIS_RECONNECT_INTERVAL_SECONDS` e `REDIS_SOCKET_TIMEOUT_SECONDS`. (#5)
- `LICENSE` (MIT), `CHANGELOG.md`, `.dockerignore` e `.github/dependabot.yml`. (#2)
- Fluxo de trabalho permanente no `CLAUDE.md` e skill `release` em `.claude/skills/release/SKILL.md`. (#1)

### Alterado

- **BREAKING** `/v1/trading-days` rejeita com `400` períodos fora da janela do calendário. Antes, um período não coberto devolvia `200` com lista vazia — afirmando que a B3 não teve nenhum dia de negociação no período — ou, com `exclude=true`, devolvia **todos** os dias do período como "sem negociação". (#6)
- **BREAKING** `/v1/trading-days` limita o intervalo por requisição a `MAX_RANGE_DAYS` (3660 por padrão), respondendo `400` acima disso. Um único request com intervalo aberto consumia ~77 s de CPU, ~117 MB de memória e devolvia ~38 MB — congelando o worker inteiro, inclusive `/v1/health`. (#6)
- **BREAKING** `/v1/trading-days` responde `422` para data mal formada, seguindo a convenção do FastAPI. Antes respondia `400`, e o regex aceitava datas impossíveis como `2024-13-45`. (#6)
- **BREAKING** `/v1/health` responde `503` quando o estado é `unhealthy`. Antes respondia `200` nos três estados, o que tornava impossível ao `HEALTHCHECK` do Docker e a probes `httpGet` do Kubernetes detectarem qualquer falha. (#7)
- **BREAKING** `/v1/health` considera a expiração do cache e ambas as chaves. Um cache de dez horas era reportado como `degraded` enquanto `/v1/hours` já respondia `503` para o mesmo estado. (#7)
- **BREAKING** `/v1/hours`, `/v1/hours/open` e `/v1/hours/close` respondem `404` quando o Redis está disponível e a chave não existe. Antes respondiam `503 "Redis indisponível"`, uma afirmação falsa que levava o operador a depurar rede e DNS quando a correção era um único `SET`. (#7)
- **BREAKING** Os mesmos endpoints respondem `502` quando o valor armazenado não está no formato `HH:MM`, em vez de servir o valor inválido como `200`. (#7)
- A janela de datas deixa de ser anunciada como "a partir de 01/01/2006". A cobertura é móvel e passa a ser consultável em `GET /v1/calendar-info`. (#6)
- `/v1/hours` lê as duas chaves num único `MGET`. As leituras sequenciais anteriores não eram atômicas: um escritor concorrente podia produzir uma resposta com o horário de abertura de ontem e o de fechamento de hoje. (#4)

### Removido

- `pytz`, substituído por `zoneinfo` da biblioteca padrão. (#5)
- A configuração `min_date_year`. A validação passa a derivar dos limites reais do calendário. (#6)
- `.github/workflows/docker-build.yml`, absorvido pelo `ci.yml`. O workflow anterior construía e publicava a imagem sem executar nenhuma verificação, e sobrescrevia a tag `latest` a partir de qualquer branch. (#9)

### Corrigido

- `cp .env.example .env`, o caminho de setup documentado no README, impedia a aplicação de iniciar. O `pydantic-settings` usa `extra="forbid"` por padrão e rejeitava a chave `REDIS_URL_ENV`, que não mapeava para nenhum campo do modelo. (#5)
- A API não se recuperava de uma queda do Redis. Quando o ping inicial falhava, o cliente era descartado, e como a inicialização só acontecia no construtor, a resposta era `503` para sempre — mesmo depois de o Redis voltar. Só um restart resolvia. (#7)
- Uma falha na construção do calendário derrubava o processo **antes** de o uvicorn abrir a porta, sem health endpoint e em crash-loop. Agora a falha é registrada, a aplicação sobe, apenas os endpoints de data respondem `503`, e o `/v1/health` torna o estado visível. (#4)
- Uma chave contendo string vazia era tratada como ausente, fazendo um Redis saudável responder `503`. (#7)
- Idade de cache exatamente `0.0` era reportada como ausência de cache, e um cache recém-populado era classificado como `unhealthy` — os dois estados estavam semanticamente invertidos. (#7)
- O cliente Redis síncrono era chamado de handlers `async def`, bloqueando o event loop por até 5 s por requisição. Migrado para `redis.asyncio`. (#4)
- `.gitignore` ignorava `.DS_Store/` com barra final, padrão que casa apenas com diretórios; os arquivos continuavam rastreados. (#2)

### Segurança

- **8 CVEs corrigidas** por atualização de dependências, encontradas pelo `pip-audit` na primeira execução do pipeline. Em `starlette` (0.38.6 → 1.6.0): SSRF em `StaticFiles` (PYSEC-2026-2281, diretamente relevante porque a documentação passou a ser servida por `StaticFiles`), validação ausente do header `Host` permitindo divergência entre `request.url.path` e o path roteado (PYSEC-2026-161), autoridade da URL sob controle do atacante (PYSEC-2026-248), e limites de formulário ignorados (PYSEC-2026-249, PYSEC-2026-1943). Em `pytest` (8.4.2 → 9.1.1): PYSEC-2026-1845. (#9)
- A URL do Redis deixa de ser logada crua. No formato documentado (`redis://user:pass@host:6379`) isso escrevia a senha em texto puro no stdout e em qualquer agregador de logs. (#10)
- `/docs` e `/redoc` passam a servir os assets localmente. O `/redoc` carregava `cdn.redoc.ly/redoc/latest/...` — origem de terceiro, sem versão fixa e sem SRI — apesar do código afirmar "without CDN", e o `/docs` caía no CDN default do FastAPI. Além do risco de supply chain, as páginas ficavam em branco em rede sem egress ou sob CSP. (#10)
- `allow_credentials` desligado no CORS. Combinado com `allow_origins=["*"]`, o Starlette passava a refletir o `Origin` do chamador, o que equivale a confiar em toda origem com credenciais. Métodos restritos a `GET` e `OPTIONS`. (#10)
- A imagem roda como usuário sem privilégios (`app`, uid 1001) e não contém mais `pip`, `setuptools` nem `wheel`, que eram fonte de CVE de severidade alta herdada da base (CVE-2026-24049, CVE-2026-23949) e permitiam `pip install` dentro de um container comprometido. Patches de segurança do sistema aplicados no build cobrem CVE-2026-53615. (#10)
- `uvicorn` passa a rodar com `--proxy-headers` e `--forwarded-allow-ips`. Sem eles, atrás do Kong em outro host os headers `X-Forwarded-Proto`/`For` eram descartados, e URLs geradas e redirecionamentos saíam como `http://` num site HTTPS. (#10)
- `pandas` passa a ser declarado e pinado. Era dependência direta resolvida apenas de forma transitiva por `exchange-calendars`, que não impõe constraint de versão — cada rebuild da imagem instalava uma versão arbitrária. (#2)

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

[Não publicado]: https://github.com/rlquilez/b3datetime/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/rlquilez/b3datetime/compare/v2.0.4...v2.1.0
[2.0.4]: https://github.com/rlquilez/b3datetime/compare/v2.0.3...v2.0.4
[2.0.3]: https://github.com/rlquilez/b3datetime/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/rlquilez/b3datetime/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/rlquilez/b3datetime/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/rlquilez/b3datetime/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/rlquilez/b3datetime/releases/tag/v1.0.0
