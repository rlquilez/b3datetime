# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não publicado]

### Adicionado

- `API_KEY_REQUIRED` (padrão `false`): quando `true`, o OpenAPI declara o esquema de segurança `ApiKeyAuth` (header `apikey`) como requisito global, o Swagger UI exibe **Authorize** e `GET /` informa `authentication.required: true`. É só metadado — a validação continua no Kong e a aplicação não autentica nada. (#24)
- Tags com descrição e ordem fixa, `502` documentado em `/v1/hours*`, exemplo de resposta em `GET /v1/calendar-info`, descrição em todos os campos, tabela de códigos de resposta na descrição da API, link para o README em `externalDocs` e schemas nomeados para `cache` e `calendar` de `/v1/health` e para `GET /`. O JSON das respostas não muda. (#24)

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

### Adicionado

- `GET /v1/calendar-info`, expondo `coverage_start`, `coverage_end`, `first_session`, `last_session`, `sessions_count` e `max_range_days`. (#6)
- Suíte de testes com 136 casos e 99,8% de coverage, incluindo um teste de regressão nomeado por defeito corrigido. (#8)
- Pipeline de CI com lint (ruff), tipagem (mypy), testes em Python 3.11 e 3.12, SAST (bandit, CodeQL), CVEs em dependências (pip-audit), varredura de segredos (gitleaks), scan de imagem e filesystem (Trivy), SBOM e quality gate bloqueante do SonarQube. (#9)
- Workflow de release disparado por tag, que valida a consistência da versão e retagueia a imagem com o semver sem rebuild. (#11)
- Variáveis de configuração `MAX_RANGE_DAYS`, `CALENDAR_START_OFFSET_YEARS`, `REDIS_RECONNECT_INTERVAL_SECONDS` e `REDIS_SOCKET_TIMEOUT_SECONDS`. (#5)
- `LICENSE` (MIT), `CHANGELOG.md`, `.dockerignore` e `.github/dependabot.yml`. (#2)
- Fluxo de trabalho permanente no `CLAUDE.md` e skill `release` em `.claude/skills/release/SKILL.md`. (#1)

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

### Removido

- `pytz`, substituído por `zoneinfo` da biblioteca padrão. (#5)
- A configuração `min_date_year`. A validação passa a derivar dos limites reais do calendário. (#6)
- `.github/workflows/docker-build.yml`, absorvido pelo `ci.yml`. O workflow anterior construía e publicava a imagem sem executar nenhuma verificação, e sobrescrevia a tag `latest` a partir de qualquer branch. (#9)

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

[Não publicado]: https://github.com/rlquilez/b3datetime/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/rlquilez/b3datetime/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/rlquilez/b3datetime/releases/tag/v1.0.0
