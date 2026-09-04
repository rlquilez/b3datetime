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

FastAPI service exposing B3 (Brazilian stock exchange) trading hours and trading-day calendar over REST. Two data sources: trading hours come from **Redis** (written by something outside this repo), trading days come from the **`exchange_calendars` BVMF calendar** built in-process. Deployed as a Docker image behind **Kong Gateway**.

## Commands

Local `python3` on this machine is 3.9.6 and the project needs **3.11+**. There is no 3.11 interpreter installed, so the practical way to run tests and lint locally is Docker, which also matches the deployed runtime exactly:

```bash
docker run --rm -v "$PWD":/app -w /app python:3.11-slim bash -c \
  'pip install -q -r requirements-dev.txt && python -m pytest'
```

With a 3.11+ interpreter available:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

uvicorn src.main:app --reload --port 8000   # or: python -m src

ruff check . && ruff format --check . && mypy src
pytest                  # ~200 tests (`pytest --co -q | tail -1`), coverage gate at 90% (currently ~99.8%)
pytest -m "not slow"    # skips the tests that build the real BVMF calendar

docker build -t b3datetime:ci . && IMAGE=b3datetime:ci scripts/smoke_image.sh   # the CI smoke test, locally
```

Docs at `/docs`, `/redoc`, `/openapi.json` — all assets served locally from `src/static/assets/`, no CDN. The assets live in a subdirectory on purpose: mounting the package directory itself served `__init__.py` (`tests/api/test_static.py::test_static_nao_serve_o_pacote`).

Seed Redis so `/v1/hours` returns 200 rather than 404:

```bash
redis-cli SET b3:trading:hours:open "10:00"
redis-cli SET b3:trading:hours:close "18:00"
```

## Architecture

**Nothing does I/O at import time.** Services are built in `lifespan` (`main.py`) and stored on `app.state`; routers receive them via `Depends` (`src/dependencies.py`). This is load-bearing — see below.

### Invariants that exist because of specific bugs

Each of these has a named regression test. Reverting any of them makes a specific test fail — that was verified, not assumed.

- **No import-time I/O.** The calendar used to be built at import and raised `RuntimeError` on failure, killing the process *before uvicorn bound a port* — no health endpoint, no traceback, just a crash-loop. Now a calendar failure is logged, the app still serves, date endpoints return 503, and `/v1/health` reports it. `tests/api/test_app.py::test_import_nao_faz_io` runs the import in a subprocess against a closed port.
- **The Redis client is never set to `None`.** The old code discarded it when the initial ping failed, and since init only ran in `__init__`, the API returned 503 *forever* even after Redis came back. Reconnection is lazy and throttled by `redis_reconnect_interval_seconds`; `is_connected()` goes through `_ensure_client()` on purpose, because orchestrators poll `/v1/health` and that is what drives recovery in practice.
- **Coverage is not the same as first/last session.** `TradingCalendar` tracks the requested date window separately from the first/last actual session. A window starting on a holiday still *covers* that day. Conflating them made the API reject a period it can answer.
- **Compare with `is not None`, never truthiness,** for Redis values and cache ages. An empty-string value and an age of exactly `0.0` are both legitimate, and were being read as "absent" — turning a healthy Redis into a 503 and a fresh cache into `unhealthy`.
- **Missing key and unavailable Redis are different.** 404 vs 503. Collapsing them made the API claim "Redis indisponível" when the fix was one `SET`.
- **`/v1/health` returns 503 when `unhealthy`.** With 200 in every state, the Dockerfile `HEALTHCHECK` and k8s probes could never detect a failure.
- **`/v1/trading-days` bounds the range.** `max_range_days` plus a hashed membership set. An unbounded range cost ~77 s of CPU and ~117 MB on the event loop.
- **`scope["path"]` always starts with `scope["root_path"]`** (`src/middleware.py`, `RootPathPrefixMiddleware`). Kong strips the prefix (`strip_path: true`) while `ROOT_PATH` keeps it in `root_path`; Starlette ≥ 0.35 relies on the ASGI contract in `get_route_path()`, so plain routes still matched but `Mount("/static")` propagated a `root_path` that `StaticFiles` could not strip — every asset 404'd and the docs rendered blank in production while the suite stayed green. `tests/api/test_proxy_prefix.py::test_static_atras_do_kong_com_strip_path_true`.
- **No trailing-slash redirects** (`redirect_slashes=False`). Starlette built the `Location` from `scope["path"]` (no prefix) and the incoming `Host` — behind Kong with `preserve_host: false`, the upstream's internal IP:port. `tests/api/test_proxy_prefix.py::test_barra_final_nao_redireciona_para_host_interno`.

### The calendar window

`build_bvmf_calendar` keeps the deliberate `pd.Timestamp.now(...) - pd.DateOffset(years=N)` computation and reads `.sessions` directly instead of calling `sessions_in_range()`. Both work around `parse_date` / `DateOutOfBounds` failures in `exchange_calendars` (commits `2b4bc6d`..`ebd0a07`). **Do not "simplify" either without reproducing those failures first.** The `start`/`end` keyword arguments exist so tests can request a small window.

The window is **moving** — it shifts daily. Validation derives from the calendar's real bounds *per request*, never from a constant, and never frozen at import. `GET /v1/calendar-info` exposes it. The old `min_date_year = 2006` constant is gone: it disagreed with the actual window, and the mismatch was returning wrong financial data with HTTP 200.

Any test touching the **real** calendar must pass explicit `start`/`end`, or it rots as the clock moves. That is why the default fixture is a synthetic `TradingCalendar`.

### Reverse proxy

- `ROOT_PATH` carries the Kong prefix; a trailing slash is normalized in `create_app`. It must not collide with a route prefix of the API itself (`/v1`, `/docs`, `/redoc`, `/static`, `/openapi.json`) — the middleware's "already prefixed?" check would be ambiguous.
- **Both Kong modes work.** `strip_path: true` (default): the prefix arrives stripped and `RootPathPrefixMiddleware` re-adds it to `scope["path"]`/`raw_path`. `strip_path: false` or `uvicorn --root-path`: the path already carries it and the middleware is a no-op. The `proxy_mode` fixture runs the page/asset/endpoint tests in all three shapes.
- `/docs` and `/redoc` reference `./openapi.json` and `./static/…` **relatively** (constant `OPENAPI_RELATIVE_URL`): the browser resolves them against the public URL, which is the only thing that works regardless of proxy config. The regression test parses the HTML and fetches every referenced asset the way the browser would (`test_paginas_referenciam_assets_que_respondem`).
- The container runs uvicorn with `--proxy-headers --forwarded-allow-ips "*"`.
- **CORS must be owned by exactly one layer.** The app sends permissive CORS without credentials; if Kong's CORS plugin is also on, duplicate headers make browsers reject the response.

### Auth

The API **authenticates nothing** — there is no apikey code here. Kong validates the header upstream; the endpoint docs mention it for client-facing documentation only.

## Testing

`tests/` splits into `unit/`, `api/`, `integration/`. No `__init__.py`; `--import-mode=importlib`.

- **`fakeredis`, not a hand-rolled stub.** A dict stub returns `None` where real Redis returns `""` — it would *agree with* the empty-string bug. `FakeServer.connected` toggled mid-test is the only clean way to express "Redis went down and came back".
- **Injected clock (`now_fn`) in unit tests.** `RedisCache` captures its time function at construction, so monkeypatching `get_current_datetime` silently misses.
- **`freezegun` only at the API level**, never around calendar construction (known flake with `pd.Timestamp.now()`).
- **`Settings(_env_file=None)` in every fixture**, so a developer's local `.env` cannot change results.
- `ASGITransport` does **not** run lifespan; the `lifespan_app` fixture uses `asgi-lifespan` for the wiring tests.
- **`proxy_mode` / `proxied_client`** (`tests/conftest.py`) parametrize a test over the three proxy shapes (no proxy, Kong stripped, Kong unstripped); `ProxyMode.upstream()` converts a public path into what the app actually receives. With `ROOT_PATH` set, FastAPI overwrites `scope["root_path"]` before the middleware stack, so the bug shape is simply `client.get("/docs")` against an app created with `root_path="/b3datetime"`.
- `scripts/smoke_image.sh` drives the **built image** (no Redis / Redis + `ROOT_PATH`, both path shapes, trailing slash, negatives, Docker `HEALTHCHECK`); `curl --path-as-is` is what lets the traversal cases reach the app.
- The performance test asserts **scaling**, not wall time: with `max_range_days` capping the span, even the quadratic version finishes in ~0.1 s, so an absolute threshold would pass with the bug present.

Integration tests against real Redis auto-skip when none is reachable, and use **db 15** because teardown calls `flushdb`.

## CI/CD

`.github/workflows/ci.yml` — lint, mypy, tests (3.11 + 3.12 with a Redis service), bandit, pip-audit, dependency-review, gitleaks, CodeQL, Trivy (fs + image), SonarQube with a **blocking** quality gate, multi-arch publish, SBOM, and a `ci-ok` aggregator meant to be the single required status check.

- **No `tags:` trigger** — `release.yml` owns tags. That is how double-publishing is prevented structurally.
- `latest` is `enable={{is_default_branch}}`. It used to be unconditional, so a push to any branch overwrote production `latest`.
- The `test` job greps `coverage.xml` for `filename="src/`. Coverage is configured with `include` (not `source`) precisely so paths are root-relative; otherwise SonarQube silently reports **0%**.
- `docker-verify` builds amd64 with `load: true` so Trivy has something to scan, and needs no secrets (works on fork PRs).

`.github/workflows/release.yml` — on `v*` tags: verifies the tag is on `main` and that `api_version`, README and CHANGELOG agree, extracts the CHANGELOG section, retags the image at the manifest level (no rebuild), and publishes the Release. It does **not** touch `latest`.

## Conventions

- Docstrings, comments, OpenAPI `description`/`summary` text, and commit messages are **pt-BR**. Identifiers are English.
- Endpoints carry heavy OpenAPI metadata. Shared `responses` blocks live in `src/routers/openapi_examples.py` — that module is CPD-excluded, so put genuinely shared examples there rather than duplicating them.
- Do **not** pass `response_model=` when the handler has a return annotation; FastAPI infers it and Sonar flags the duplication (`python:S8409`).
- Response models are Pydantic classes declared in the router that uses them.
- All "now" goes through `get_current_datetime()` with the settings timezone. Never bare `datetime.now()` — ruff's `DTZ` rules enforce this.
- Both `requirements.txt` and `requirements-dev.txt` pin exact versions. `pandas` and `starlette` are pinned deliberately: `exchange-calendars` declares no pandas constraint, and FastAPI declares no starlette upper bound.
- `pytest` runs with `filterwarnings = ["error"]`. A new pydantic deprecation fails the suite at import — that is intentional.
- `.history/` is VS Code Local History noise — never read, edit, or grep it.
- The version lives in `src/config.py` (`api_version`) and is duplicated in `README.md` and `CHANGELOG.md`. `release.yml` enforces the agreement. See the `release` skill.
