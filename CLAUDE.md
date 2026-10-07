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

**Production is public and unauthenticated**: base `https://api.quilez.cloud/b3datetime/v1/`, docs at `https://api.quilez.cloud/b3datetime/docs`, `ROOT_PATH=/b3datetime`, Kong `strip_path: true`. Production pulls the `latest` image automatically after `docker-publish` on `main`, so "verify in production" means: CI green → wait for the pull → `curl` the public URL without any header. **`GET /` returns `build`** — the commit SHA baked into the image (`ARG BUILD_SHA` → `APP_BUILD` → `Settings.app_build`, `local` outside a published image), passed identically to the verify, e2e and publish builds — so "is production on the new image?" is `curl -s …/b3datetime/ | jq -r .build` against `git rev-parse HEAD` (#66). The README documents the real URL with cURL/Python examples that must keep working as written (run them after touching endpoints). The one thing that must never appear in the repo is the upstream's **internal** address (it used to leak through the trailing-slash redirect).

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

uvicorn --app-dir src --factory b3datetime.main:create_app --reload --port 8000   # or: PYTHONPATH=src python -m b3datetime

ruff check . && ruff format --check . && mypy   # mypy is strict over src, scripts and tests (targets come from pyproject)
pytest                  # ~520 tests (`pytest --co -q | tail -1`; the e2e ones are deselected), coverage gate at 90% (currently 100%)
pytest tests/unit --cov-fail-under=0   # one block (each CI job runs one; a single block's coverage is partial)
pytest -m "not slow"    # skips the tests that build the real BVMF calendar (all in tests/integration)

docker build -t b3datetime:ci . && IMAGE=b3datetime:ci scripts/smoke_image.sh   # the CI smoke test, locally

docker build -t b3datetime:e2e . && E2E_IMAGE=b3datetime:e2e python -m pytest -m e2e tests/e2e --no-cov   # the CI e2e job

# the CI dast job (~3 min): stack up, ZAP on the compose network, tripwire, stack down
IMAGE=b3datetime:ci docker compose -f tests/stack/compose.yaml up -d --wait
docker build -t b3datetime-zap tests/dast && mkdir -p zap && chmod 777 zap
docker run --rm --network b3stack_default -v "$PWD/tests/dast:/zap/plano:ro" -v "$PWD/zap:/zap/wrk:rw" b3datetime-zap zap.sh -cmd -autorun /zap/plano/plano-imagem.yaml
python scripts/dast_resumo.py zap/zap.json zap/arvore.yaml tests/contract/openapi.json

# the CI performance job (~35 s of load), on the same stack
docker build -t b3datetime-k6 tests/load && mkdir -p k6 && chmod 777 k6
docker run --rm --network b3stack_default -v "$PWD/tests/load:/scripts:ro" -v "$PWD/k6:/out:rw" b3datetime-k6 run --quiet --summary-export=/out/k6.json /scripts/smoke.js
python scripts/k6_resumo.py k6/k6.json tests/load/smoke.js tests/contract/openapi.json
E2E_BASE_URL=https://api.quilez.cloud/b3datetime python -m pytest -m e2e tests/e2e --no-cov   # read-only e2e against production
```

The e2e suite talks to the containers through ports published on `127.0.0.1`, so it needs a Python 3.14 **on the host** — a container can't reach them. `uv` already has a managed CPython 3.14 here: `uv venv --python 3.14 <dir> && uv pip install --python <dir>/bin/python -r requirements-dev.txt`.

Docs at `/docs`, `/redoc`, `/openapi.json` — all assets served locally from `src/b3datetime/static/assets/`, no CDN. The assets live in a subdirectory on purpose: mounting the package directory itself served `__init__.py` (`tests/api/test_static.py::test_static_nao_serve_o_pacote`).

Seed Redis so `/v1/hours` returns 200 rather than 404:

```bash
redis-cli SET b3:trading:hours:open "10:00"
redis-cli SET b3:trading:hours:close "18:00"
```

## Architecture

**src layout: the package is `b3datetime`, at `src/b3datetime/`** (imports are `b3datetime.*`; pytest has `pythonpath = ["src", "."]`; the image copies it to `/app/b3datetime`; uvicorn runs `b3datetime.main:create_app --factory`). It used to be a package literally named `src`, which mutmut 3 refuses outright (`assert not name.startswith("src.")` in `stats.record_trampoline_hit`) and which other tools treat as a layout directory rather than a package (#52). Coverage paths still start with `src/`, so the `filename="src/` tripwire and `sonar.sources=src` are unchanged.

The module map lives in the README (`Arquitetura → Mapa de módulos`, a Mermaid diagram) — keep it in sync when adding a module. Routers: `root.py` (`GET /`), `hours.py`, `dates.py`, `health.py`; shared OpenAPI metadata (tags, security scheme, examples) in `routers/openapi_examples.py`; `middleware.py` holds the proxy-prefix middleware.

**Nothing does I/O at import time.** Services are built in `lifespan` (`main.py`) and stored on `app.state`; routers receive them via `Depends` (`src/b3datetime/dependencies.py`). This is load-bearing — see below. That includes **settings**: there is no module-level `settings`, `TZ` or `app` (uvicorn runs in factory mode). `SettingsDep` resolves `request.app.state.settings` (the ones passed to `create_app`), never the process-global `get_settings()` — which only `create_app()` without arguments uses. `get_current_datetime(tz)` takes the timezone explicitly. `ROOT_EXAMPLE` is built from the fields' *defaults*, so the OpenAPI example (and the contract snapshot) do not depend on the machine's environment (#60).

### Invariants that exist because of specific bugs

Each of these has a named regression test. Reverting any of them makes a specific test fail — that was verified, not assumed.

- **No import-time I/O.** The calendar used to be built at import and raised `RuntimeError` on failure, killing the process *before uvicorn bound a port* — no health endpoint, no traceback, just a crash-loop. Now a calendar failure is logged, the app still serves, date endpoints return 503, and `/v1/health` reports it. `tests/api/test_app.py::test_import_nao_faz_io` runs the import in a subprocess against a closed port.
- **The Redis client is never set to `None`.** The old code discarded it when the initial ping failed, and since init only ran in `__init__`, the API returned 503 *forever* even after Redis came back. Reconnection is lazy and throttled by `redis_reconnect_interval_seconds`; `is_connected()` goes through `_ensure_client()` on purpose, because orchestrators poll `/v1/health` and that is what drives recovery in practice.
- **Coverage is not the same as first/last session.** `TradingCalendar` tracks the requested date window separately from the first/last actual session. A window starting on a holiday still *covers* that day. Conflating them made the API reject a period it can answer.
- **Elapsed time is measured on instants, not wall clocks.** Cache age and the reconnect throttle go through `_segundos_entre()` (both datetimes converted to UTC). Subtracting two aware datetimes with the *same* `ZoneInfo` returns the wall-clock difference — across a DST fall-back, 2 real hours were 1 h, so an expired cache was still served (#61). The test `FakeClock.advance` advances real time (adds in UTC) for the same reason.
- **Compare with `is not None`, never truthiness,** for Redis values and cache ages. An empty-string value and an age of exactly `0.0` are both legitimate, and were being read as "absent" — turning a healthy Redis into a 503 and a fresh cache into `unhealthy`.
- **Missing key and unavailable Redis are different.** 404 vs 503. Collapsing them made the API claim "Redis indisponível" when the fix was one `SET`.
- **`InvalidUpstreamValueError` is the only source of 502.** It is raised when Redis answers with a value outside the contract: not `HH:MM` (the hours router builds its models through `_horarios`/`_horario`, which translate pydantic's `ValidationError`), or not UTF-8 (`_as_str`, or redis-py itself raising `UnicodeDecodeError` inside `MGET` under `decode_responses=True`). The old handler mapped **every** `ValidationError` to 502, so an internal bug looked like bad Redis data, and non-UTF-8 bytes were a 500. `TIME_PATTERN` uses `[0-9]`, never `\d` — pydantic-core's `\d` is Unicode and accepted `1\u0660:00` (#59).
- **`/v1/health` returns 503 when `unhealthy`.** With 200 in every state, the Dockerfile `HEALTHCHECK` and k8s probes could never detect a failure.
- **`/v1/trading-days` bounds the range.** `max_range_days` plus a hashed membership set. An unbounded range cost ~77 s of CPU and ~117 MB on the event loop.
- **`scope["path"]` always starts with `scope["root_path"]`** (`src/b3datetime/middleware.py`, `RootPathPrefixMiddleware`). Kong strips the prefix (`strip_path: true`) while `ROOT_PATH` keeps it in `root_path`; Starlette ≥ 0.35 relies on the ASGI contract in `get_route_path()`, so plain routes still matched but `Mount("/static")` propagated a `root_path` that `StaticFiles` could not strip — every asset 404'd and the docs rendered blank in production while the suite stayed green. `tests/api/test_proxy_prefix.py::test_static_atras_do_kong_com_strip_path_true`.
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

`tests/` splits into **blocks — one directory, one CI job each**: `unit/` (no I/O), `api/` (the "component" block: the whole ASGI app in process, no lifespan, no I/O), `integration/` (real Redis on db 15, the real BVMF calendar, the real lifespan), `property/` (Hypothesis), `e2e/` (the image). **`tests/README.md` is the test-architecture doc** (rationale, Mermaid diagrams, tripwires) — keep it in sync with any change to the suite or to `ci.yml`. No `__init__.py`; `--import-mode=importlib`.

- **`tests/property/` is the Hypothesis block.** Profiles live in `tests/conftest.py` and are picked by `HYPOTHESIS_PROFILE`: `dev` (100 examples, default), `ci` (500, `deadline=None`, `print_blob`), `mutation` (25, `derandomize`, no database). CI passes `--hypothesis-seed`/`--randomly-seed` = `$GITHUB_RUN_ID`, so a re-run reproduces and each push explores new inputs. Write the property *before* the fix: `test_redact_url.py` failed 4 of 5 properties on the old `redact_url` (#58) while the 12 example tests passed.
- **Schemathesis fuzzes the whole API from its own OpenAPI** (`tests/property/test_api_schemathesis.py`, marker `api_fuzz`): in process, on the real app, with only the lifespan swapped for one that injects the doubles (`app.router.lifespan_context`). Schemathesis 4 runs every app on one shared event loop and keeps the lifespan open; the fixture calls `shutdown_lifespans()`, and a module-scoped filter ignores the `ResourceWarning` from its never-closed anyio streams. `positive_data_acceptance` is excluded only for `/v1/trading-days` (documented 400 for schema-valid but domain-invalid ranges).
- **Anything that opens a socket or builds the real calendar belongs in `tests/integration/`** (its `conftest.py` owns `real_redis` and `lifespan_app`), so `unit/` and `api/` stay I/O-free. The oracle of B3 calendar rules lives in `tests/e2e/calendario_b3.py` (importable without the `e2e` marker; tested by itself in `tests/unit/test_calendario_b3.py`) and is used both by the e2e suite and by `tests/integration/test_calendario_bvmf.py` (real `exchange_calendars`, 2017–2025).
- **Each CI block runs `pytest tests/<dir> --cov-fail-under=0` with `COVERAGE_FILE=coverage-<bloco>.dat`** and uploads that plus `junit-<bloco>.xml`. The 90% gate is applied once, to the sum, by the `coverage` job (`coverage combine`), which also runs `scripts/consolidar_testes.py`: no skipped test in any block, no empty block, `src/` paths in `coverage.xml`. Never pass `-m` to a block run without `and not e2e` — a CLI `-m` replaces the one in `addopts`. The data files are not dot-files on purpose: `upload-artifact` skips hidden files.

- **`fakeredis`, not a hand-rolled stub.** A dict stub returns `None` where real Redis returns `""` — it would *agree with* the empty-string bug. `FakeServer.connected` toggled mid-test is the only clean way to express "Redis went down and came back".
- **Injected clock (`now_fn`) in unit tests.** `RedisCache` captures its time function at construction, so monkeypatching `get_current_datetime` silently misses.
- **`freezegun` only at the API level**, never around calendar construction (known flake with `pd.Timestamp.now()`).
- **`Settings(_env_file=None)` in every fixture**, so a developer's local `.env` cannot change results.
- `ASGITransport` does **not** run lifespan; the `lifespan_app` fixture (`tests/integration/conftest.py`) uses `asgi-lifespan` for the wiring tests.
- **`proxy_mode` / `proxied_client`** (`tests/conftest.py`) parametrize a test over the three proxy shapes (no proxy, Kong stripped, Kong unstripped); `ProxyMode.upstream()` converts a public path into what the app actually receives. With `ROOT_PATH` set, FastAPI overwrites `scope["root_path"]` before the middleware stack, so the bug shape is simply `client.get("/docs")` against an app created with `root_path="/b3datetime"`.
- `scripts/smoke_image.sh` drives the **built image** (no Redis / Redis + `ROOT_PATH`, both path shapes, trailing slash, negatives, Docker `HEALTHCHECK`); `curl --path-as-is` is what lets the traversal cases reach the app.
- The performance test asserts **scaling**, not wall time: with `max_range_days` capping the span, even the quadratic version finishes in ~0.1 s, so an absolute threshold would pass with the bug present.

Integration tests against real Redis auto-skip when none is reachable (locally), and use **db 15** because teardown calls `flushdb`. In CI the integration job has a Redis service and the `coverage` job fails on any skip.

### E2E (`tests/e2e/`)

Black-box, against the **real image** with real Redis and the real BVMF calendar. The `e2e` marker is deselected by default (`-m "not e2e"` in `addopts`), so the regular run and its no-skip tripwire are unaffected; run it with `-m e2e --no-cov` (coverage is meaningless for code running in a container, and `fail_under` would fail it).

- **Two modes.** `E2E_IMAGE=<image>` starts four containers — `principal` (seeded Redis + `ROOT_PATH`, Kong `strip_path: true` shape), `sem_redis` (closed port), `sem_calendario` (`EXCHANGE_NAME=INEXISTENTE`, so the calendar never builds), `redis_tardio` (its Redis is started mid-test) — on a per-run Docker network with unique names, and removes them at the end, dumping `docker logs` on failure. `E2E_BASE_URL=<url>` runs only what reads; cases needing other environments or Redis control skip with the reason.
- **100% is enforced, not promised.** `test_contrato.py::CASOS` holds one or more cases per (operation, status) pair, and `test_cobertura_de_100_por_cento_do_contrato` requires that set to **equal** the pairs in the `/openapi.json` the container serves (8 operations, 23 pairs today). A new route or response code without an e2e case fails the pipeline; so does a case for an undocumented code.
- **Contract validation** (`contrato.py`): responses with a documented `schema` (200, 422, health 503) go through `jsonschema` Draft 2020-12 — OpenAPI 3.1's dialect — with `$ref`s resolved against the whole served document; example-only responses (the 400/404/502/503 error envelopes) must match an example's shape: no undocumented field, compatible types, same `error` category, non-empty `message`.
- **Domain checks never hardcode a year**: dates derive from today and from `/v1/calendar-info`, because the window moves. Holiday rules verified against the real calendar for 2017–2026: fixed national holidays, 24/12 and 31/12, Carnival Mon/Tue, Good Friday and Corpus Christi are always closed (Easter computed locally), Ash Wednesday trades, **20/11 only from 2024** (B3 traded on it in 2020 and 2023), and a year has 245–251 sessions.
- `test_resiliencia.py` proves the "Redis client is never `None`" invariant on the real container: 503 while the Redis hostname doesn't exist, then healthy without a restart once that container starts (`REDIS_RECONNECT_INTERVAL_SECONDS=1`).

## CI/CD

`.github/workflows/ci.yml` — lint, mypy, tests as one job per block (matrix `tests`: unit, component, integration with a Redis service; Python 3.14 only — the image's runtime; the 3.11 entry was dropped in #45), a `coverage` job that combines them and owns the 90% gate and the tripwires, bandit, pip-audit, dependency-review, gitleaks, CodeQL, Trivy (fs + image), SonarQube with a **blocking** quality gate, multi-arch publish, SBOM, automatic release, and a `ci-ok` aggregator meant to be the single required status check.

- **The only workflow, with no `tags:` trigger.** Version tags are *created* by the `release` job after publishing; nothing reacts to a tag push, so double-publishing stays structurally impossible. (`release.yml` used to be triggered by tags and was folded in here in #41.)
- `latest` is `enable={{is_default_branch}}`. It used to be unconditional, so a push to any branch overwrote production `latest`.
- The `coverage` job (via `scripts/consolidar_testes.py`) checks `coverage.xml` for `filename="src/`. Coverage is configured with `include` (not `source`) precisely so paths are root-relative; otherwise SonarQube silently reports **0%**. It also fails if any `junit-<bloco>.xml` records a skipped test — with the Redis service up, `slow` and `integration` must actually run. Sonar reads `junit-*.xml` (Ant pattern).
- `docker-verify` builds amd64 with `load: true` so Trivy has something to scan, and needs no secrets (works on fork PRs). Its smoke step runs `scripts/smoke_image.sh` against the built image: no Redis (health 503), then real Redis + `ROOT_PATH` in both Kong path shapes, every page/asset/endpoint, trailing slash, negatives and the Docker `HEALTHCHECK`.
- **The base is `python:3.14-alpine` pinned by digest** (both stages). Dependabot proposes the new digest weekly and the PR's CI scans it before adoption; Python minor/major bumps are ignored in `dependabot.yml` on purpose. The Debian `slim` base carried 173 Trivy alerts in code scanning, 150 of them with no Debian fix, for packages the app never runs (#39). Every compiled dependency ships musllinux cp314 wheels, so the builder has no compiler — a dependency without one fails the build visibly.
- **`APK_REFRESH` changes on every run.** `docker-verify` exports `run_id-run_attempt` and `docker-publish` reuses that same value, so the published amd64 layer is the scanned one. Without it, the GHA cache served the old `apt-get upgrade` layer for as long as the base digest stayed the same: Debian's patches never landed, and from 2026-09-14 the blocking Trivy failed every build (#39). The heavy dependency layer sits *before* the `ARG` and stays cached.
- **Separate GHA cache scopes** — `verify` (amd64) and `publish` (multi-arch; also reads `verify`). The cache index is last-writer-wins per scope; with a shared scope, the amd64-only export of `docker-verify` erased the arm64 entries and every publish redid the arm64 `pip install` under QEMU (~200 s).
- `sonar` is skipped for Dependabot PRs (`github.actor == 'dependabot[bot]'`) as well as fork PRs: they get no secrets, and the job used to fail on an empty `SONAR_HOST_URL`, painting every Dependabot PR red. It also `ls`es `coverage.xml`/`junit.xml` after the artifact download so a broken download cannot turn into a silent 0%.
- `dependency-review` is in `ci-ok` (it needs the repository's Dependency graph enabled — it is, via `PUT /repos/{owner}/{repo}/vulnerability-alerts`).
- **`e2e` job** — runs `tests/e2e` against the **exact image `docker-verify` built, smoke-tested and scanned**: `docker-verify` exports it (`docker save | gzip`, artifact `imagem`, 1-day retention) and the e2e job `docker load`s it — it used to rebuild the Dockerfile from the GHA cache, same steps but not guaranteed the same bits. It is in `ci-ok`. `E2E_BUILD=${{ github.sha }}` makes it assert `GET /` `build`. A second tripwire fails it if `e2e-junit.xml` records any skip: in containers every environment exists, so a skip would be a documented response left unvalidated. The README's cURL and Python examples run as part of it (`test_exemplos_do_readme.py`): every block that uses the public URL is executed, with only the URL rewritten.
- **`release` job — automatic release.** It runs after `docker-publish` on `main`. When the commit's `api_version` has no Release yet, it: validates strict SemVer; checks `gh release view` — only the exact stderr `release not found` means "absent", any other failure fails the job so a transient API error can never move tags; requires a pre-existing tag (a run interrupted midway) to point at `GITHUB_SHA`; extracts the CHANGELOG section with `awk` (fails if empty); runs `crane tag` from the digest `docker-publish` just pushed, to `X.Y.Z`, plus `X.Y` and `X` unless it is a pre-release; then `gh release create vX.Y.Z --target $GITHUB_SHA`. Otherwise it does nothing. Every step is idempotent — "Re-run failed jobs" resumes, and the digest output is preserved. `crane` rather than `buildx imagetools create`, because this registry does not implement the OCI referrers API (502). It does **not** touch `latest`, and it stays out of `ci-ok` because it runs after publishing. The version-sync checks the old tag workflow did now live in `tests/unit/test_config.py` and run before anything is published — including `test_secao_do_changelog_da_versao_atual_nao_vazia`, because an empty section would otherwise fail only *after* `latest` moved.
- **`docker-publish` depends on `ci-ok`** (plus `docker-verify` for the `apk-refresh` output). It used to depend only on `docker-verify`, `e2e` and `sonar`, so a failing bandit, CodeQL, gitleaks, Trivy fs or pip-audit still let `latest` reach production (#51). `ci-ok` accepts `skipped` only where skipping is the design: `dependency-review` (PR-only) always, `sonar` only outside `push` (Dependabot/fork PRs get no secrets). On `push`, any other skip fails it — otherwise a skipped block would publish. It also writes a per-block table to the run summary. **`docker-publish`, `release` and `sbom` use explicit `if:` conditions** (`!cancelled() && needs.<x>.result == 'success'`): the implicit `success()` is evaluated over the *transitive* `needs` chain, and `dependency-review` is `skipped` on every push — with the implicit check the publish was skipped even with `ci-ok` green.
- **Architecture is enforced, not described** (`Arquitetura` job): `lint-imports` (`[tool.importlinter]`: layers `__main__ > main > routers > dependencies > services > config`, independent routers, no `fastapi`/`starlette`/`uvicorn` in `services`/`config`, `redis`/`pandas`/`uvicorn` confined to their module, leaf modules, acyclic siblings) plus `tests/architecture/`: an audit-hook subprocess proves `import b3datetime.main` opens no socket, spawns nothing and reads nothing from the working directory (a planted `.env`), and AST rules turn the conventions below into checks (no module-level `Settings()`/`get_settings()`/`create_app()`, no `Depends(get_settings)`, services built only in `lifespan`, response models local to their router, every router published). A new router must be added to `ROUTERS` there.
- **`dast` job — OWASP ZAP, blocking, in `ci-ok`.** Active scan (Automation Framework plan `tests/dast/plano-imagem.yaml`) of the same `imagem` artifact, behind `tests/stack/compose.yaml` (seeded Redis, `ROOT_PATH`); ZAP is pinned by digest in `tests/dast/Dockerfile` (Dependabot `docker` covers `/tests/dast`). Any alert Low or above fails it (`exitStatus`). Traps: the `alertFilter` job must come **before** the scans — filters only apply to alerts raised after it; the edge-owned header rules (10038 CSP, 10020 anti-clickjacking, 10021 nosniff) are downgraded to Info, never dropped; the only false positives are 10096 on `/static/*.js` and rule 2 on `redoc.standalone.js` (ReDoc's `ipv4` sample `192.168.0.1`) — keep each filter's URL scope minimal and its reason in the plan. `scripts/dast_resumo.py` requires **every contract operation in ZAP's exported sites tree with a 2xx**: before the `start`/`end` parameter examples existed, ZAP sent `start=start`, got 422 on every request and never reached the endpoint logic — so a new query parameter needs an `openapi_examples` that yields 200. No SARIF upload on purpose (informational header alerts would sit open in code scanning forever). It is the only scanner that sees the vendored JS (`static/assets/`): it found DOMPurify 3.1.4 inside Swagger UI 5.17.14 (#69). Never run the active plan against production.
- **`performance` job — k6, blocking, in `ci-ok`.** `tests/load/smoke.js` on the same stack: every contract operation at a constant rate (`mix`), `/v1/trading-days` at the maximum span with `exclude=true` (`caro`) and `/v1/health` during both. Thresholds: no failed request, no failed check, **no dropped iteration**, p95 < 250 ms per endpoint (750 ms for `caro`), and health-under-load p95 < **5× the idle health p95 measured in `setup()` of the same run** (floor 10 ms) — relative, so a slow shared runner passes and a blocked event loop does not. The window comes from `/v1/calendar-info` at run time, never a fixed date. k6 2.3.0 is pinned by digest in `tests/load/Dockerfile` (Dependabot `docker` covers `/tests/load`). `scripts/k6_resumo.py` fails on an endpoint with no samples (a p95 threshold over zero samples passes silently) and on any crossed threshold; `tests/unit/test_scripts_k6_resumo.py` requires `ENDPOINTS` in the script to equal the contract's paths — **a new endpoint needs a k6 entry**. Seen failing: `time.sleep(0.1)` in the period logic crosses 10 thresholds (exit 99). Measured: the worst case costs 3–8 ms and health under load is ~1.4× idle, so `get_trading_days` stays `async def`. `tests/load/**` is excluded from Sonar (k6 runtime globals like `__ENV`).
- **Mutation testing is blocking** (`mutation` job, `[tool.mutmut]` + `scripts/mutation_gate.py`): score = detected/evaluated must stay ≥ `[tool.b3datetime.quality] mutation_min_score` (99%; ratchet, only goes up; 99.59% — 730/733, 3 documented equivalents — at #66). Traps: mutmut refuses a package named `src` (hence the src layout); `--no-cov` in `pytest_add_cli_args` is mandatory (with coverage on, every partial run fails `fail_under` and every mutant looks killed); **mutmut does not mutate decorated functions**, so handler logic lives in plain functions (`_dias_do_periodo`, `_montar_health`, `_metadados`, `_horarios`…) — keep new endpoint logic out of the `@router.get` body; `# pragma: no mutate` only works on a *statement* line or a compound header (a comment inside a multi-line call is ignored), so write the equivalent expression on one line and put the reason after the pragma; module-level code (and `_example`, run at import) is never mutated. The selection excludes `integration` (parallel workers share Redis db 15 and `flushdb` each other → random kills) and the `tempo` marker (timing assertions blow up under N workers): a mutant's verdict must not depend on the machine. A new survivor means a missing test — exact messages, boundaries — unless it is genuinely equivalent. mutmut runs the suite inside `mutants/`, which only gets `src/`, `tests/`, `pyproject.toml` and `also_copy`: **a repo file a test reads must be in `also_copy`**, or the clean run fails and the whole job dies before any mutant (the #67 push, with `.github/workflows/ci.yml`); `tests/architecture/test_convencoes.py::test_sandbox_da_mutacao_tem_todo_arquivo_que_os_testes_leem` checks every `RAIZ / "…"`/`REPO_ROOT / "…"` read.
- **Dead code is a failing check** (`Código morto` job): `vulture` (`[tool.vulture]`, confidence 60, decorator-registered handlers ignored, reviewed whitelist in `tests/dead_code/vulture_whitelist.py` — references to the real symbols, never executed), `deptry . --config tests/dead_code/deptry.toml` (its config is *not* in `pyproject.toml`: with a `[project]` table present deptry ignores the requirements files) and `pytest --dead-fixtures -m "e2e or not e2e"`. Code only the tests call is dead too — delete it rather than whitelisting it (#64 removed `TradingCalendar._sessions`, `RedisCache.get/clear`, `RedisService.timezone`).
- **The OpenAPI contract is versioned** in `tests/contract/openapi.json`, generated by `PYTHONPATH=src python scripts/gerar_openapi.py` (in process, `ROOT_PATH=/b3datetime`, `Settings(_env_file=None)` — byte-identical to what production serves). `tests/api/test_openapi.py::test_snapshot_do_contrato_esta_em_dia` fails when it drifts, so every contract change shows in the diff. The `contract` job (`Contrato · oasdiff`) compares it with the snapshot at the latest `v*` tag and **fails on a breaking change unless the `api_version` MAJOR went up** — every push deploys, so the break and the bump land together. Releases before the snapshot existed (≤ v2.0.4) fall back to production's `/openapi.json`. `review: false`/`github-token: ""` keep the spec from leaving CI.
- **SAST also covers the workflows**: CodeQL runs `python` and `actions` (matrix), and `zizmor` (pinned in `requirements-dev.txt`) audits `.github/` — SARIF to code scanning, then a blocking run with `GH_TOKEN` for the online audits. It is clean even under `--persona=pedantic`; the `auditor`-only `secrets-outside-env` would need GitHub environments (repository settings), a deliberate non-goal. Every `permissions:` block carries a comment, and `dependabot.yml` has a 7-day `cooldown` on every ecosystem (supply-chain window). The Redis image has **one source**, `tests/stack/compose.yaml` (Dependabot `docker-compose` updates its digest): the e2e conftest and the smoke script read it, and `tests/unit/test_imagens_fixadas.py` requires the `ci.yml` service to carry the same digest and forbids a mutable `redis:<tag>` anywhere. The same compose file is the app+seeded-Redis stack the DAST and k6 jobs bring up.
- **Actions are pinned by commit SHA** with a `# vX.Y.Z` comment (Dependabot keeps both in sync), every checkout sets `persist-credentials: false`, every job has `timeout-minutes`, and `${{ }}` reaches `run:` only through `env:` (template injection). Job names follow `Bloco · ferramenta`.
- **A re-run only republishes the current `main`.** The first step of `docker-publish` fails when `run_attempt > 1` and `main` has moved past `GITHUB_SHA`: production pulls `latest` automatically, so re-running an old run would roll it back.

## Conventions

- Docstrings, comments, OpenAPI `description`/`summary` text, and commit messages are **pt-BR**. Identifiers are English.
- Endpoints carry heavy OpenAPI metadata. Shared `responses` blocks live in `src/b3datetime/routers/openapi_examples.py` — that module is CPD-excluded, so put genuinely shared examples there rather than duplicating them.
- Do **not** pass `response_model=` when the handler has a return annotation; FastAPI infers it and Sonar flags the duplication (`python:S8409`).
- Response models are Pydantic classes declared in the router that uses them.
- All "now" goes through `get_current_datetime()` with the settings timezone. Never bare `datetime.now()`/`date.today()`/`time.time()` in `src/` — ruff's `DTZ` rules and the `TID251` banned-api list in `pyproject.toml` enforce it (only `config.py` is exempt).
- **Lint and typing are at their strictest on purpose.** ruff selects pylint, mccabe (`max-complexity = 10`), FastAPI (`FAST001` is Sonar's `S8409`), `ERA` (commented-out code), `ARG`, `PERF`, `BLE`, `PGH` and more; `TC` stays off because moving imports under `TYPE_CHECKING` breaks FastAPI/pydantic's runtime annotation resolution under 3.14's deferred annotations. mypy is `strict` with the pydantic plugin over `src`, `scripts` and `tests` — test doubles go through `tests.conftest.as_redis()` (a documented `cast`) instead of `# type: ignore`. The `Lint · infra` job runs actionlint, hadolint (every `Dockerfile`, threshold `info`) and shellcheck.
- Both `requirements.txt` and `requirements-dev.txt` pin exact versions. `pandas` and `starlette` are pinned deliberately: `exchange-calendars` declares no pandas constraint, and FastAPI declares no starlette upper bound.
- **Dependabot PRs are never merged.** Their bumps are consolidated into one commit on `main` (to the latest versions on PyPI, not just the PR's), and Dependabot closes the PRs itself ("up-to-date now" / "Superseded"). `dependabot.yml` groups pip minor+patch into one weekly PR (majors stay separate) and all actions into one: with one PR per package, the 5-PR `open-pull-requests-limit` filled up and updates silently stopped (#40).
- `pytest` runs with `filterwarnings = ["error"]`. A new pydantic deprecation fails the suite at import — that is intentional.
- `.history/` is VS Code Local History noise — never read, edit, or grep it.
- The version lives in `src/b3datetime/config.py` (`api_version`) and is duplicated in **`pyproject.toml`**, `README.md` (`Versão atual: X`) and `CHANGELOG.md`; `tests/unit/test_config.py` enforces all of them before any publish. **Never push a tag by hand**: the release commit on `main` is the whole release, and the CI's `release` job creates the tag, the image tags and the GitHub Release. See the `release` skill.
- Tag names, the security scheme and shared examples live in `src/b3datetime/routers/openapi_examples.py`; the OpenAPI contract test derives the route set from `app.routes` (flattening FastAPI's `_IncludedRouter`), so a new router shows up there automatically and must get a row in `DOCUMENTED_CODES`.
- CHANGELOG sections follow the canonical order of the `release` skill: Adicionado, Alterado, Descontinuado, Removido, Corrigido, Segurança.
