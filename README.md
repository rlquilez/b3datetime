<div align="center">
  <img src=".github/logo.svg" alt="B3 DateTime API Logo" width="400">

  <h1>B3 DateTime API</h1>

  <p>API REST em Python para consultar horários de operação e dias de negociação da B3 (Bolsa de Valores de São Paulo)</p>

  <p><strong>Versão atual: 2.0.0</strong></p>
</div>

## 📋 Descrição

A B3 DateTime API oferece endpoints para:
- Consultar horários de abertura e fechamento da bolsa (via Redis com cache local de 1h)
- Validar se determinada data é dia de negociação
- Listar dias de negociação ou não negociação em um período
- Consultar a janela de datas coberta pelo calendário
- Verificar a saúde da aplicação e suas dependências

Utiliza o calendário BVMF (B3/Bovespa) do módulo `exchange_calendars`.

## 🏗️ Arquitetura

```
┌─────────────┐      ┌──────────────┐      ┌──────────────┐
│   Cliente   │ ───▶ │ Kong Gateway │ ───▶ │  B3 API      │
└─────────────┘      └──────────────┘      │  (FastAPI)   │
                            │               └──────┬───────┘
                            │                      │
                            ▼                      ▼
                     ┌──────────────┐      ┌──────────────┐
                     │   API Key    │      │    Redis     │
                     │  Management  │      │ (Cache 1h)   │
                     └──────────────┘      └──────────────┘
```

**Características**:
- **FastAPI** com documentação OpenAPI/Redoc servida **localmente** (sem CDN)
- **Redis assíncrono** (`redis.asyncio`), leitura atômica via `MGET` e reconexão automática
- **Cache local** com fallback de até 1 hora quando o Redis está indisponível
- **Exchange Calendars**: calendário oficial BVMF, com janela de cobertura consultável
- **Timezone**: `America/Sao_Paulo` em todas as operações
- **Docker multi-arch** (linux/amd64, linux/arm64), rodando como usuário sem privilégios
- **CI/CD** com testes, análise estática, varredura de segurança e quality gate

## 🚀 Endpoints

### Horários de Operação

#### `GET /v1/hours`
Retorna horários de abertura e fechamento. As duas chaves são lidas numa **única operação atômica**, de modo que a resposta nunca combina um horário de abertura antigo com um de fechamento novo.

```json
{ "open": "10:00", "close": "18:00" }
```

```bash
curl -H "apikey: YOUR_API_KEY" https://api.example.com/v1/hours
```

#### `GET /v1/hours/open` · `GET /v1/hours/close`
Retornam apenas um dos horários.

```json
{ "time": "10:00" }
```

**Códigos de resposta dos três endpoints:**

| Código | Situação |
|--------|----------|
| `200` | Valor obtido do Redis, ou do cache local com menos de 1h |
| `404` | Redis **disponível**, mas a chave não existe — basta um `SET` |
| `502` | O valor armazenado no Redis não está no formato `HH:MM` |
| `503` | Redis indisponível e cache ausente ou expirado |

### Dias de Negociação

#### `GET /v1/calendar-info`
Retorna a janela de datas que o calendário sabe responder. **Consulte este endpoint em vez de assumir uma data mínima fixa**: a janela é móvel e se desloca conforme o tempo passa.

```json
{
  "exchange": "BVMF",
  "coverage_start": "2016-08-17",
  "coverage_end": "2027-08-17",
  "first_session": "2016-08-17",
  "last_session": "2027-08-17",
  "sessions_count": 2730,
  "max_range_days": 3660
}
```

`coverage_*` é o intervalo respondível; `first_session`/`last_session` são o primeiro e o último **pregão** dentro dele. Os dois diferem quando a janela começa num feriado ou fim de semana.

#### `GET /v1/is-trading-day`
Verifica se hoje é dia de negociação na B3.

```json
{ "date": "2024-01-15", "is_trading_day": true }
```

Responde `503` se a data atual estiver fora da janela do calendário — nunca `false`, que seria indistinguível de um feriado legítimo.

#### `GET /v1/trading-days`
Lista dias de negociação (ou de não negociação) em um período.

**Parâmetros:**
- `start` (obrigatório): data inicial, `YYYY-MM-DD`
- `end` (obrigatório): data final, `YYYY-MM-DD`, maior ou igual a `start`
- `exclude` (opcional): `true` para listar dias **sem** negociação; `false` (padrão) para listar dias **com** negociação

**Restrições:**
- O período deve estar **inteiramente** dentro da janela do calendário (`GET /v1/calendar-info`). Fora dela, a resposta é `400` — a API não devolve resultado parcial em silêncio.
- O intervalo máximo por requisição é `max_range_days` (3660 dias por padrão). Períodos maiores são rejeitados com `400`.

```bash
# Dias COM negociação
curl -H "apikey: YOUR_API_KEY" \
  "https://api.example.com/v1/trading-days?start=2024-01-01&end=2024-01-31"

# Dias SEM negociação (feriados e finais de semana)
curl -H "apikey: YOUR_API_KEY" \
  "https://api.example.com/v1/trading-days?start=2024-01-01&end=2024-01-31&exclude=true"
```

| Código | Situação |
|--------|----------|
| `200` | Lista obtida |
| `400` | `end` < `start`, período fora da janela, ou intervalo acima do máximo |
| `422` | Formato de data inválido |
| `503` | Calendário indisponível |

### Health Check

#### `GET /v1/health`

| Estado | HTTP | Situação |
|--------|------|----------|
| `healthy` | `200` | Redis conectado e calendário carregado |
| `degraded` | `200` | Redis desconectado, mas **ambas** as chaves têm cache local válido |
| `unhealthy` | **`503`** | Sem cache utilizável, cache expirado, ou calendário indisponível |

O `503` em `unhealthy` é o que permite ao `HEALTHCHECK` do Docker e a probes `httpGet` do Kubernetes detectarem a falha.

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00-03:00",
  "redis_status": "connected",
  "cache": {
    "redis_connected": true,
    "open_cache_age_seconds": 120,
    "close_cache_age_seconds": 120,
    "open_cache_expired": false,
    "close_cache_expired": false,
    "cache_ttl_seconds": 3600
  },
  "calendar": {
    "available": true,
    "first_session": "2016-08-17",
    "last_session": "2027-08-17",
    "sessions_count": 2730
  }
}
```

### Informações da API

#### `GET /`
Metadados, endpoints disponíveis e forma de autenticação.

## 🔐 Autenticação

**Nenhuma no momento.** As requisições não precisam de header algum:

```bash
curl https://api.quilez.cloud/b3datetime/v1/hours
```

Quando o Kong Gateway passar a exigir o header `apikey` (plugin key-auth), a API é publicada com `API_KEY_REQUIRED=true`: o OpenAPI declara o esquema `ApiKeyAuth`, o Swagger UI exibe **Authorize** e `GET /` informa `authentication.required: true`. **A aplicação não valida chaves** — não há nenhum código de autenticação nela; quem valida é o Kong.

## ⚙️ Variáveis de Ambiente

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `REDIS_URL_ENV` | URL de conexão do Redis (nome preferencial) | `redis://localhost:6379` |
| `REDIS_URL` | Alternativa aceita, com precedência **menor** que `REDIS_URL_ENV` | — |
| `REDIS_KEY_OPEN` | Chave Redis do horário de abertura | `b3:trading:hours:open` |
| `REDIS_KEY_CLOSE` | Chave Redis do horário de fechamento | `b3:trading:hours:close` |
| `CACHE_TTL_SECONDS` | Validade do cache local, em segundos | `3600` |
| `TIMEZONE` | Timezone das operações | `America/Sao_Paulo` |
| `EXCHANGE_NAME` | Bolsa do `exchange_calendars` | `BVMF` |
| `CALENDAR_START_OFFSET_YEARS` | Anos para trás na construção do calendário | `10` |
| `MAX_RANGE_DAYS` | Intervalo máximo em `/v1/trading-days` | `3660` |
| `REDIS_RECONNECT_INTERVAL_SECONDS` | Intervalo mínimo entre tentativas de reconexão | `30` |
| `REDIS_SOCKET_TIMEOUT_SECONDS` | Timeout de socket do Redis | `5` |
| `ROOT_PATH` | Prefixo para proxy reverso (ex.: `/b3datetime`) | vazio |

`REDIS_URL` é aceito porque é o nome que Heroku, Railway, Render, Fly.io e templates de `docker-compose` injetam automaticamente. Quando as duas estão definidas, **`REDIS_URL_ENV` vence**.

**Exemplo (`.env`):**
```env
REDIS_URL_ENV=redis://localhost:6379
REDIS_KEY_OPEN=b3:trading:hours:open
REDIS_KEY_CLOSE=b3:trading:hours:close
```

## 💾 Cache e Fallback

1. **Leitura primária**: um único `MGET` no Redis
2. **Cache local**: se o Redis falhar, usa o valor em memória enquanto tiver menos de 1 hora
3. **Erro 503**: Redis indisponível e cache ausente ou expirado

O cliente Redis **nunca é descartado**: se o Redis estiver fora no start do processo e voltar depois, a API se recupera sozinha, sem restart. As tentativas de reconexão são espaçadas por `REDIS_RECONNECT_INTERVAL_SECONDS`.

## 🌐 Proxy reverso (Kong)

- `ROOT_PATH` deve conter o prefixo (ex.: `/b3datetime`). Barra final é normalizada. O prefixo não pode coincidir com uma rota da própria API (`/v1`, `/docs`, `/redoc`, `/static`, `/openapi.json`).
- **Os dois modos do Kong funcionam.** Com `strip_path: true` (padrão) o prefixo chega removido e um middleware o recompõe no scope ASGI — sem isso, `/static/*` respondia `404` e a documentação ficava em branco. Com `strip_path: false` o prefixo já vem no caminho e nada é alterado.
- **Barra final não redireciona**: `/docs/` e `/v1/hours/` respondem `404`. O redirecionamento anterior era montado com o header `Host` recebido do proxy e apontava para o endereço interno do upstream.
- O container roda o uvicorn com `--proxy-headers` e `--forwarded-allow-ips`, para que `X-Forwarded-Proto` e `X-Forwarded-For` sejam respeitados.
- **CORS deve ser configurado em uma única camada.** A aplicação emite CORS permissivo sem credenciais; se o Kong também tiver o plugin de CORS ativo, os headers duplicados fazem o browser rejeitar a resposta.

## 🐳 Docker

```bash
docker build -t b3datetime:latest .

docker run -d \
  -p 8000:8000 \
  -e REDIS_URL_ENV=redis://redis-host:6379 \
  --name b3datetime \
  b3datetime:latest
```

A imagem roda como usuário sem privilégios (`app`, uid 1001) e não contém `pip`, `setuptools` nem `wheel`.

### Docker Compose

```yaml
services:
  redis:
    image: redis:7.4-alpine
    ports: ["6379:6379"]

  b3datetime:
    build: .
    ports: ["8000:8000"]
    environment:
      - REDIS_URL_ENV=redis://redis:6379
    depends_on: [redis]
```

## 💻 Desenvolvimento Local

### Pré-requisitos
- **Python 3.11 ou superior** (a imagem roda 3.11)
- Redis (opcional — a suíte de testes usa `fakeredis`)

```bash
git clone https://github.com/rlquilez/b3datetime.git
cd b3datetime

python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt
cp .env.example .env

uvicorn src.main:app --reload --port 8000
# ou: python -m src
```

Documentação: http://localhost:8000/docs · http://localhost:8000/redoc · http://localhost:8000/openapi.json

### Qualidade

```bash
ruff check .            # lint
ruff format .           # formatação
mypy src                # tipagem
pytest                  # testes + coverage (mínimo de 90%)
pytest -m "not slow"    # pula os testes que constroem o calendário real
```

Os testes de integração contra Redis real dão *skip* automático quando não há Redis em `localhost:6379`.

## 📊 Preparando o Redis

```bash
redis-cli SET b3:trading:hours:open "10:00"
redis-cli SET b3:trading:hours:close "18:00"
```

Se as chaves não existirem, `/v1/hours` responde **404** (e não 503): o Redis está no ar, falta apenas o valor.

## 🔧 Tecnologias

- **[FastAPI](https://fastapi.tiangolo.com/)** · **[Uvicorn](https://www.uvicorn.org/)** · **[Redis](https://redis.io/)**
- **[exchange_calendars](https://github.com/gerrymanoim/exchange_calendars)** · **[Pydantic](https://docs.pydantic.dev/)**
- **[pytest](https://docs.pytest.org/)** · **[ruff](https://docs.astral.sh/ruff/)** · **[mypy](https://mypy-lang.org/)**
- **[Docker](https://www.docker.com/)** · **[GitHub Actions](https://github.com/features/actions)** · **[SonarQube](https://www.sonarsource.com/)**

## 📝 Limitações e Considerações

- **Janela de datas**: o calendário cobre uma janela móvel (10 anos para trás por padrão). Consulte `GET /v1/calendar-info` — não há data mínima fixa.
- **Intervalo máximo**: `/v1/trading-days` aceita no máximo `MAX_RANGE_DAYS` dias por requisição.
- **Timezone**: todas as operações usam `America/Sao_Paulo`.
- **Cache TTL**: o cache local expira em 1 hora.
- **Horários estáticos**: os horários vindos do Redis não consideram pregões especiais.

## 🚀 CI/CD

Pipeline em `.github/workflows/ci.yml`, disparado em push na `main`, em pull request e manualmente:

| Etapa | Ferramenta |
|-------|-----------|
| Lint e formatação | ruff |
| Tipagem | mypy |
| Testes e coverage | pytest (Python 3.11 e 3.12, com Redis real) |
| SAST | bandit, CodeQL |
| CVEs em dependências | pip-audit, dependency-review |
| Segredos | gitleaks |
| Imagem e filesystem | Trivy |
| Qualidade | SonarQube com quality gate **bloqueante** |
| Publicação | imagem multi-arch + SBOM |

Nenhuma imagem é publicada sem que lint, tipagem, testes, scan da imagem e o quality gate passem.

`.github/workflows/release.yml` é disparado por tag `v*`: valida a consistência da versão, retagueia a imagem com o semver e publica a Release.

**Secrets necessários:** `GIT_REGISTRY`, `GIT_OWNER`, `GIT_REGISTRY_USER`, `GIT_REGISTRY_PASSWORD`, `SONAR_TOKEN`, `SONAR_HOST_URL`.

## 🔄 Migração da v1 para a v2

A v2.0.0 corrige respostas que antes eram silenciosamente erradas. As mudanças de contrato:

| Endpoint | Antes (v1) | Agora (v2) | Por quê |
|----------|-----------|-----------|---------|
| `/v1/hours*` | `503` quando a chave não existia | **`404`** | O Redis estava no ar; dizer "indisponível" mandava o operador depurar rede e DNS quando faltava um `SET` |
| `/v1/hours*` | `200` com valor fora de `HH:MM` | **`502`** | Valor inválido no Redis não deve ser servido como válido |
| `/v1/health` | `200` mesmo em `unhealthy` | **`503`** em `unhealthy` | Com 200 em todos os estados, o `HEALTHCHECK` e as probes nunca detectavam falha |
| `/v1/health` | `degraded` com cache expirado | `unhealthy` | `/v1/hours` já respondia 503 no mesmo estado; os dois endpoints se contradiziam |
| `/v1/trading-days` | `200 []` fora da janela | **`400`** | Devolvia lista vazia, afirmando que a bolsa não operou no período |
| `/v1/trading-days` | `200` com todos os dias, em `exclude=true` | **`400`** | Marcava o período inteiro como sem negociação |
| `/v1/trading-days` | intervalo ilimitado | **`400`** acima de `MAX_RANGE_DAYS` | Um único request consumia ~77 s de CPU e ~117 MB |
| `/v1/trading-days` | `400` para data mal formada | **`422`** | Convenção do FastAPI para erro de validação |

**Ações necessárias:**
1. Trate `404` e `502` em `/v1/hours*` (antes tudo era `503`).
2. Ajuste monitoramento que dependa de `/v1/health` responder `200` — `unhealthy` agora é `503`.
3. Substitua qualquer data mínima fixa (`2006-01-01`) por uma consulta a `GET /v1/calendar-info`.
4. Divida consultas com intervalo acima de `MAX_RANGE_DAYS`.

## 📄 Licença

MIT — veja [LICENSE](LICENSE).

## 👤 Autor

Rodrigo Quilez ([@rlquilez](https://github.com/rlquilez))

## 🤝 Contribuindo

Contribuições são bem-vindas. Abra uma issue ou pull request.

## 📚 Documentação Adicional

- [CHANGELOG.md](CHANGELOG.md)
- [Documentação FastAPI](https://fastapi.tiangolo.com/)
- [Exchange Calendars](https://github.com/gerrymanoim/exchange_calendars)
- [Redis Python Client](https://redis-py.readthedocs.io/)
- [Kong Gateway](https://docs.konghq.com/)
