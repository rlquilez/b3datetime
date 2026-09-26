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

**Production is public and unauthenticated**: base `https://api.quilez.cloud/b3datetime/v1/`, docs at `https://api.quilez.cloud/b3datetime/docs`, `ROOT_PATH=/b3datetime`, Kong `strip_path: true`. Production pulls the `latest` image automatically after `docker-publish` on `main`, so "verify in production" means: CI green → wait for the pull → `curl` the public URL without any header. The README documents the real URL with cURL/Python examples that must keep working as written (run them after touching endpoints). The one thing that must never appear in the repo is the upstream's **internal** address (it used to leak through the trailing-slash redirect).

## Commands

Local `python3` on this machine is 3.9.6 and the project needs **3.14** (the image's runtime and the only version in `requires-python`). There is no 3.14 interpreter installed, so the practical way to run tests and lint locally is Docker, on the same base as the production image (Python 3.14 on Alpine — no `bash`, hence `sh -c`):

```bash
docker run --rm -v "$PWD":/app -w /app python:3.14-alpine sh -c \
  'pip install -q -r requirements-dev.txt && python -m pytest'
```

With a 3.14 interpreter available:

```bash
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

uvicorn src.main:app --reload --port 8000   # or: python -m src

ruff check . && ruff format --check . && mypy src
pytest                  # ~240 tests (`pytest --co -q | tail -1`; the e2e ones are deselected), coverage gate at 90% (currently ~99.8%)
pytest -m "not slow"    # skips the tests that build the real BVMF calendar

docker build -t b3datetime:ci . && IMAGE=b3datetime:ci scripts/smoke_image.sh   # the CI smoke test, locally

docker build -t b3datetime:e2e . && E2E_IMAGE=b3datetime:e2e python -m pytest -m e2e tests/e2e --no-cov   # the CI e2e job
E2E_BASE_URL=https://api.quilez.cloud/b3datetime python -m pytest -m e2e tests/e2e --no-cov   # read-only e2e against production
```

The e2e suite talks to the containers through ports published on `127.0.0.1`, so it needs a Python 3.14 **on the host** — a container can't reach them. `uv` already has a managed CPython 3.14 here: `uv venv --python 3.14 <dir> && uv pip install --python <dir>/bin/python -r requirements-dev.txt`.

Docs at `/docs`, `/redoc`, `/openapi.json` — all assets served locally from `src/static/assets/`, no CDN. The assets live in a subdirectory on purpose: mounting the package directory itself served `__init__.py` (`tests/api/test_static.py::test_static_nao_serve_o_pacote`).

Seed Redis so `/v1/hours` returns 200 rather than 404:

```bash
redis-cli SET b3:trading:hours:open "10:00"
redis-cli SET b3:trading:hours:close "18:00"
```

## Architecture

The module map lives in the README (`Arquitetura → Mapa de módulos`, a Mermaid diagram) — keep it in sync when adding a module. Routers: `root.py` (`GET /`), `hours.py`, `dates.py`, `health.py`; shared OpenAPI metadata (tags, security scheme, examples) in `routers/openapi_examples.py`; `middleware.py` holds the proxy-prefix middleware.

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

The API **authenticates nothing** — there is no apikey code here, and there must not be. **There is no authentication in production today** (Kong's key-auth is off), so the docs must not claim `apikey` is required. `API_KEY_REQUIRED` (default `false`) only drives documentation: `B3DateTimeAPI.openapi()` declares `ApiKeyAuth` + a global `security` requirement, `GET /` reports `authentication.required`, and the API description switches text (`openapi_examples.auth_description`). `tests/api/test_openapi.py::test_sem_autenticacao_por_padrao` and `::test_esquema_apikey_quando_exigido` lock both states.

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

### E2E (`tests/e2e/`)

Black-box, against the **real image** with real Redis and the real BVMF calendar. The `e2e` marker is deselected by default (`-m "not e2e"` in `addopts`), so the regular run and its no-skip tripwire are unaffected; run it with `-m e2e --no-cov` (coverage is meaningless for code running in a container, and `fail_under` would fail it).

- **Two modes.** `E2E_IMAGE=<image>` starts four containers — `principal` (seeded Redis + `ROOT_PATH`, Kong `strip_path: true` shape), `sem_redis` (closed port), `sem_calendario` (`EXCHANGE_NAME=INEXISTENTE`, so the calendar never builds), `redis_tardio` (its Redis is started mid-test) — on a per-run Docker network with unique names, and removes them at the end, dumping `docker logs` on failure. `E2E_BASE_URL=<url>` runs only what reads; cases needing other environments or Redis control skip with the reason.
- **100% is enforced, not promised.** `test_contrato.py::CASOS` holds one or more cases per (operation, status) pair, and `test_cobertura_de_100_por_cento_do_contrato` requires that set to **equal** the pairs in the `/openapi.json` the container serves (8 operations, 23 pairs today). A new route or response code without an e2e case fails the pipeline; so does a case for an undocumented code.
- **Contract validation** (`contrato.py`): responses with a documented `schema` (200, 422, health 503) go through `jsonschema` Draft 2020-12 — OpenAPI 3.1's dialect — with `$ref`s resolved against the whole served document; example-only responses (the 400/404/502/503 error envelopes) must match an example's shape: no undocumented field, compatible types, same `error` category, non-empty `message`.
- **Domain checks never hardcode a year**: dates derive from today and from `/v1/calendar-info`, because the window moves. Holiday rules verified against the real calendar for 2017–2026: fixed national holidays, 24/12 and 31/12, Carnival Mon/Tue, Good Friday and Corpus Christi are always closed (Easter computed locally), Ash Wednesday trades, **20/11 only from 2024** (B3 traded on it in 2020 and 2023), and a year has 245–251 sessions.
- `test_resiliencia.py` proves the "Redis client is never `None`" invariant on the real container: 503 while the Redis hostname doesn't exist, then healthy without a restart once that container starts (`REDIS_RECONNECT_INTERVAL_SECONDS=1`).

## CI/CD

`.github/workflows/ci.yml` — lint, mypy, tests (Python 3.14 only — the image's runtime; the 3.11 matrix entry was dropped in #45 — with a Redis service), bandit, pip-audit, dependency-review, gitleaks, CodeQL, Trivy (fs + image), SonarQube with a **blocking** quality gate, multi-arch publish, SBOM, automatic release, and a `ci-ok` aggregator meant to be the single required status check.

- **The only workflow, with no `tags:` trigger.** Version tags are *created* by the `release` job after publishing; nothing reacts to a tag push, so double-publishing stays structurally impossible. (`release.yml` used to be triggered by tags and was folded in here in #41.)
- `latest` is `enable={{is_default_branch}}`. It used to be unconditional, so a push to any branch overwrote production `latest`.
- The `test` job greps `coverage.xml` for `filename="src/`. Coverage is configured with `include` (not `source`) precisely so paths are root-relative; otherwise SonarQube silently reports **0%**. A second tripwire fails the job if `junit.xml` records any skipped test — with the Redis service up, `slow` and `integration` must actually run.
- `docker-verify` builds amd64 with `load: true` so Trivy has something to scan, and needs no secrets (works on fork PRs). Its smoke step runs `scripts/smoke_image.sh` against the built image: no Redis (health 503), then real Redis + `ROOT_PATH` in both Kong path shapes, every page/asset/endpoint, trailing slash, negatives and the Docker `HEALTHCHECK`.
- **The base is `python:3.14-alpine` pinned by digest** (both stages). Dependabot proposes the new digest weekly and the PR's CI scans it before adoption; Python minor/major bumps are ignored in `dependabot.yml` on purpose. The Debian `slim` base carried 173 Trivy alerts in code scanning, 150 of them with no Debian fix, for packages the app never runs (#39). Every compiled dependency ships musllinux cp314 wheels, so the builder has no compiler — a dependency without one fails the build visibly.
- **`APK_REFRESH` changes on every run.** `docker-verify` exports `run_id-run_attempt` and `docker-publish` reuses that same value, so the published amd64 layer is the scanned one. Without it, the GHA cache served the old `apt-get upgrade` layer for as long as the base digest stayed the same: Debian's patches never landed, and from 2026-09-14 the blocking Trivy failed every build (#39). The heavy dependency layer sits *before* the `ARG` and stays cached.
- **Separate GHA cache scopes** — `verify` (amd64) and `publish` (multi-arch; also reads `verify`). The cache index is last-writer-wins per scope; with a shared scope, the amd64-only export of `docker-verify` erased the arm64 entries and every publish redid the arm64 `pip install` under QEMU (~200 s).
- `sonar` is skipped for Dependabot PRs (`github.actor == 'dependabot[bot]'`) as well as fork PRs: they get no secrets, and the job used to fail on an empty `SONAR_HOST_URL`, painting every Dependabot PR red. It also `ls`es `coverage.xml`/`junit.xml` after the artifact download so a broken download cannot turn into a silent 0%.
- `dependency-review` is in `ci-ok` (it needs the repository's Dependency graph enabled — it is, via `PUT /repos/{owner}/{repo}/vulnerability-alerts`).
- **`e2e` job** — runs `tests/e2e` against the image, in parallel with `docker-verify`, after lint/typecheck/test; it is in `ci-ok` and a prerequisite of `docker-publish`. It builds from the same Dockerfile with the same `APK_REFRESH` (`run_id-run_attempt`), **reads** the `verify` cache scope and writes none (writing would race `docker-verify` for the last-writer-wins index). A second tripwire fails it if `e2e-junit.xml` records any skip: in containers every environment exists, so a skip would be a documented response left unvalidated.
- **`release` job — automatic release.** It runs after `docker-publish` on `main`. When the commit's `api_version` has no Release yet, it: validates strict SemVer; checks `gh release view` — only the exact stderr `release not found` means "absent", any other failure fails the job so a transient API error can never move tags; requires a pre-existing tag (a run interrupted midway) to point at `GITHUB_SHA`; extracts the CHANGELOG section with `awk` (fails if empty); runs `crane tag` from the digest `docker-publish` just pushed, to `X.Y.Z`, plus `X.Y` and `X` unless it is a pre-release; then `gh release create vX.Y.Z --target $GITHUB_SHA`. Otherwise it does nothing. Every step is idempotent — "Re-run failed jobs" resumes, and the digest output is preserved. `crane` rather than `buildx imagetools create`, because this registry does not implement the OCI referrers API (502). It does **not** touch `latest`, and it stays out of `ci-ok` because it runs after publishing. The version-sync checks the old tag workflow did now live in `tests/unit/test_config.py` and run before anything is published — including `test_secao_do_changelog_da_versao_atual_nao_vazia`, because an empty section would otherwise fail only *after* `latest` moved.
- **A re-run only republishes the current `main`.** The first step of `docker-publish` fails when `run_attempt > 1` and `main` has moved past `GITHUB_SHA`: production pulls `latest` automatically, so re-running an old run would roll it back.

## Conventions

- Docstrings, comments, OpenAPI `description`/`summary` text, and commit messages are **pt-BR**. Identifiers are English.
- Endpoints carry heavy OpenAPI metadata. Shared `responses` blocks live in `src/routers/openapi_examples.py` — that module is CPD-excluded, so put genuinely shared examples there rather than duplicating them.
- Do **not** pass `response_model=` when the handler has a return annotation; FastAPI infers it and Sonar flags the duplication (`python:S8409`).
- Response models are Pydantic classes declared in the router that uses them.
- All "now" goes through `get_current_datetime()` with the settings timezone. Never bare `datetime.now()` — ruff's `DTZ` rules enforce this.
- Both `requirements.txt` and `requirements-dev.txt` pin exact versions. `pandas` and `starlette` are pinned deliberately: `exchange-calendars` declares no pandas constraint, and FastAPI declares no starlette upper bound.
- **Dependabot PRs are never merged.** Their bumps are consolidated into one commit on `main` (to the latest versions on PyPI, not just the PR's), and Dependabot closes the PRs itself ("up-to-date now" / "Superseded"). `dependabot.yml` groups pip minor+patch into one weekly PR (majors stay separate) and all actions into one: with one PR per package, the 5-PR `open-pull-requests-limit` filled up and updates silently stopped (#40).
- `pytest` runs with `filterwarnings = ["error"]`. A new pydantic deprecation fails the suite at import — that is intentional.
- `.history/` is VS Code Local History noise — never read, edit, or grep it.
- The version lives in `src/config.py` (`api_version`) and is duplicated in **`pyproject.toml`**, `README.md` (`Versão atual: X`) and `CHANGELOG.md`; `tests/unit/test_config.py` enforces all of them before any publish. **Never push a tag by hand**: the release commit on `main` is the whole release, and the CI's `release` job creates the tag, the image tags and the GitHub Release. See the `release` skill.
- Tag names, the security scheme and shared examples live in `src/routers/openapi_examples.py`; the OpenAPI contract test derives the route set from `app.routes` (flattening FastAPI's `_IncludedRouter`), so a new router shows up there automatically and must get a row in `DOCUMENTED_CODES`.
- CHANGELOG sections follow the canonical order of the `release` skill: Adicionado, Alterado, Descontinuado, Removido, Corrigido, Segurança.
