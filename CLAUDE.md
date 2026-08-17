# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# Fluxo obrigatório de trabalho

**Siga SEMPRE este fluxo em qualquer ajuste nesta aplicação.** Vale para toda rodada, não só para a primeira.

1. **Monte um plano** e quebre o trabalho por partes, na divisão que fizer mais sentido.
2. **Para cada parte, crie uma Issue no GitHub** (`gh issue create`) **bem detalhada** — contexto, objetivo, escopo e critérios de aceite — com **labels coerentes ao objetivo**. Labels disponíveis: `bug`, `enhancement`, `documentation`, `release`, `ci`, `security`, `test`, `chore`, `refactor`, `dependencies`. Atenda cada uma até 100%.
3. **Avalie o resultado no GitHub Actions e no SonarQube.** Projeto `b3datetime`, servidor `https://sonarqube.quilez.cloud`. Meta: **maior coverage possível, sem duplicações e sem issues**. Use as ferramentas `mcp__sonarqube__*` — em especial `get_project_quality_gate_status` e `search_sonar_issues_in_projects`.
4. **Commit e push direto na `main`.** Sem branch, sem PR.
5. **Atualize todas as documentações relacionadas** em cada rodada (`README.md`, este arquivo, `CHANGELOG.md`, descrições OpenAPI).
6. **Ao fechar cada Issue, escreva um comentário de fechamento detalhado e classificado**: o que foi feito, decisões tomadas, arquivos e commits, métricas de CI e SonarQube, e eventuais ações pendentes do usuário.
7. **A cada nova versão, atualize a página de Releases do GitHub** em sincronia com o `CHANGELOG.md` e a convenção de versionamento — ver a skill `release` (`.claude/skills/release/SKILL.md`).
8. **Com o usuário ausente, decida autonomamente.** Nunca bloqueie aguardando resposta; escolha a melhor opção, registre a decisão e siga.

Mensagens de commit seguem [Conventional Commits](https://www.conventionalcommits.org/pt-br/) em português (`feat:`, `fix:`, `chore:`, `ci:`, `test:`, `docs:`, `refactor:`, `style:`), referenciando a Issue com `Refs #N`.

### Consequências práticas

- **O `main` é o único branch.** `git push origin main` direto. Não existe branch protection, então a disciplina é sua.
- **O quality gate é bloqueante.** Se o `ci.yml` reprovar no Sonar, a imagem não é publicada — corrija antes de seguir.
- **Security hotspots não são resolvíveis pelo CI.** A condição "hotspots revisados = 100%" do gate `Sonar way` só é satisfeita pela UI ou por `mcp__sonarqube__change_security_hotspot_status`.
- **O token `gh` pode não ter o escopo `workflow`.** Se um push que toca `.github/workflows/` for recusado, peça ao usuário `gh auth refresh -h github.com -s workflow`.

---

## What this is

FastAPI service exposing B3 (Brazilian stock exchange) trading hours and trading-day calendar over REST. Two data sources: trading hours come from **Redis** (written by something outside this repo), trading days come from the **`exchange_calendars` BVMF calendar** computed in-process. Deployed as a Docker image behind **Kong Gateway**.

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Run (dev, autoreload)
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
# or: python -m src.main   (same thing, reload enabled in __main__)

# Docker
docker build -t b3datetime:latest .
docker run -d -p 8000:8000 -e REDIS_URL_ENV=redis://redis-host:6379 b3datetime:latest

# Seed Redis so /v1/hours works at all
redis-cli SET b3:trading:hours:open "10:00"
redis-cli SET b3:trading:hours:close "18:00"
```

Docs at `/docs` (Swagger), `/redoc`, `/openapi.json`.

**There is no test suite, linter, or formatter configured** — no pytest, pyproject.toml, or CI test job. CI (`.github/workflows/docker-build.yml`) only builds and pushes a multi-arch image on push to `main` or `proxima`. Verify changes by running the server and hitting endpoints.

## Architecture

```
src/main.py              app assembly: CORS, router registration, custom /docs + /redoc, GET /
src/config.py            pydantic-settings Settings + module-level TZ, get_current_datetime(), get_min_allowed_date()
src/routers/hours.py     /v1/hours, /v1/hours/open, /v1/hours/close  → redis_service
src/routers/dates.py     /v1/is-trading-day, /v1/trading-days        → bvmf_calendar
src/routers/health.py    /v1/health
src/services/redis_service.py  Redis client + in-memory fallback cache
```

Two **module-level singletons created at import time**, and they fail differently:

- `redis_service` (`redis_service.py:184`) — a failed connect is *tolerated*: it logs and sets `redis_client = None`, so the app boots without Redis and hours endpoints degrade to cache/503.
- `bvmf_calendar` (`dates.py:20`) — a failure `raise RuntimeError` at import, which **kills app startup**. Building the calendar is the slow part of boot.

Neither is dependency-injected; routers import the singleton directly. `lifespan` in `main.py` only logs.

### Trading-hours cache semantics

`RedisService.get_value()` (`redis_service.py:92`) is the whole fallback policy: try Redis → on miss/failure use the in-memory `RedisCache` entry if younger than `cache_ttl_seconds` (3600) → otherwise raise **503**. The local cache is only ever populated by a *successful* Redis read, so a cold start with Redis down 503s immediately. `/v1/health` maps this to `healthy` / `degraded` (Redis down, cache present) / `unhealthy` (Redis down, no cache).

The Redis client is the **synchronous** `redis` package called from `async def` handlers, so every hours request blocks the event loop for up to the 5s socket timeout. Keep that in mind before adding load-bearing work here.

### The calendar date window — read before touching `dates.py`

`bvmf_calendar` is built with `start = today − 10 years`, and both endpoints query the `DatetimeIndex` at `bvmf_calendar.sessions` directly with boolean masks rather than calling `sessions_in_range()` / `is_session()`. Both choices are deliberate and recent (commits `2b4bc6d` → `ebd0a07`): they work around `exchange_calendars` `parse_date` / `DateOutOfBounds` errors. Don't "simplify" back to `sessions_in_range` or a wider `start` without reproducing those failures first.

Consequence to be aware of: `config.min_date_year = 2006` and the README still advertise data from 2006-01-01, but `/v1/trading-days` validates against 2006 while the calendar only *contains* the last 10 years. A `start` between 2006 and the window's start passes validation and silently returns no sessions for the uncovered span — which, with `exclude=true`, reports those days as non-trading. Any fix has to reconcile the validation bound, the calendar `start`, and the docs together.

### Reverse-proxy path handling

The service runs under a Kong path prefix, so path generation is customized and is easy to break:

- `root_path` comes from the `ROOT_PATH` env var (e.g. `/b3datetime`).
- FastAPI's built-in `docs_url` and `redoc_url` are disabled; `main.py` re-implements both routes so they reference **`./openapi.json` relatively**. `GET /` returns the same relative form.

Serving absolute `/openapi.json` from those pages breaks the docs behind the proxy. `/redoc` loads the ReDoc bundle and Google Fonts from CDNs despite its docstring claiming otherwise.

### Auth

The API **does not authenticate anything** — no apikey code exists here. Kong validates the `apikey` header upstream; endpoint docstrings mention it for client-facing documentation only.

## Conventions

- Docstrings, comments, `description=`/`summary=` text, and commit messages are **pt-BR**. Commits: `feat:` / `fix:` / `chore:` + infinitive Portuguese ("Adicionar…", "Atualizar…").
- Endpoints carry heavy OpenAPI metadata — `summary`, a long markdown `description`, and a `responses` dict with named examples. New endpoints are expected to match that density.
- Response shapes are Pydantic models declared in the router file that uses them; there is no shared schemas module.
- All "now" and date-boundary logic goes through `get_current_datetime()` / `TZ` from `config.py` (America/Sao_Paulo). Never `datetime.now()` bare.
- `requirements.txt` pins exact versions; the `exchange-calendars` pin in particular was moved for behavior reasons (`351a71c`).
- `.history/` is VS Code Local History noise — never read, edit, or grep it for current behavior.
- API version lives in `settings.api_version` and is duplicated in the README; bump both.
