#!/usr/bin/env bash
# Teste de fumaça da imagem Docker da B3 DateTime API.
#
# Sobe o container real em duas configurações e verifica cada página, asset e endpoint:
#   1) sem Redis e sem prefixo — o estado correto do health é `unhealthy` com 503;
#   2) com Redis real e ROOT_PATH=/b3datetime — como em produção atrás do Kong —, nas
#      duas formas que o gateway pode entregar o caminho (prefixo removido ou não),
#      mais barra final, casos negativos e o HEALTHCHECK da própria imagem.
#
# Uso: docker build -t b3datetime:ci . && IMAGE=b3datetime:ci scripts/smoke_image.sh
set -euo pipefail

IMAGE="${IMAGE:-b3datetime:ci}"
PREFIX="${PREFIX:-/b3datetime}"
PORT="${PORT:-8000}"
NET="smoke-net-$$"
BASE="http://127.0.0.1:${PORT}"
fail=0

log() { printf '%s\n' "$*" >&2; }

cleanup() {
  if [ "$fail" -ne 0 ]; then
    log "--- últimas linhas do log do container ---"
    docker logs smoke-app 2>&1 | tail -n 80 || true
  fi
  docker rm -f smoke-app smoke-redis >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# expect MÉTODO CAMINHO STATUS [regex-do-content-type] [trecho-obrigatório-no-corpo]
# --path-as-is: sem ele o curl normaliza `..` e os casos de traversal nunca chegam ao app.
expect() {
  local method=$1 path=$2 want=$3 ctype=${4:-} needle=${5:-}
  local body="" meta code ct
  local -a opts=(-sS --path-as-is)
  # `-X HEAD` faz o curl esperar um corpo que nunca vem; `-I` é o HEAD de verdade.
  if [ "$method" = HEAD ]; then opts+=(-I); else opts+=(-X "$method"); fi
  if [ -n "$needle" ]; then
    body=$(curl "${opts[@]}" -w '\n%{http_code} %{content_type}' "$BASE$path" || true)
    meta=${body##*$'\n'}
    body=${body%$'\n'*}
  else
    meta=$(curl "${opts[@]}" -o /dev/null -w '%{http_code} %{content_type}' "$BASE$path" || true)
  fi
  code=${meta%% *}
  ct=${meta#* }
  if [ "$code" != "$want" ]; then
    log "FALHA $method $path -> $code (esperado $want)"; fail=1; return
  fi
  if [ -n "$ctype" ] && ! [[ "$ct" =~ ^($ctype) ]]; then
    log "FALHA $method $path -> content-type '$ct' (esperado $ctype)"; fail=1; return
  fi
  if [ -n "$needle" ] && [[ "$body" != *"$needle"* ]]; then
    log "FALHA $method $path -> corpo sem '$needle'"; fail=1; return
  fi
  log "OK    $method $path -> $code${ct:+ ($ct)}"
}

# O uvicorn abre a porta antes de o lifespan terminar; o calendário leva segundos.
wait_ready() {
  local code
  for _ in $(seq 1 60); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/v1/health" || true)
    if [ -n "$code" ] && [ "$code" != "000" ]; then return 0; fi
    sleep 2
  done
  log "FALHA container não respondeu em 120 s"; fail=1; return 1
}

log "== 1) sem Redis, sem prefixo =="
docker run -d --name smoke-app -p "$PORT:8000" -e REDIS_URL_ENV=redis://127.0.0.1:1 "$IMAGE" >/dev/null
wait_ready
# Sem Redis, o estado correto é unhealthy com 503. Um 200 aqui significa que o health
# voltou a ser decorativo e o HEALTHCHECK não detecta nada.
expect GET /v1/health 503 application/json '"status":"unhealthy"'
expect GET / 200 application/json '"version"'
expect GET /docs 200 text/html './static/swagger-ui.css'
expect GET /static/swagger-ui.css 200 text/css
docker rm -f smoke-app >/dev/null

log "== 2) Redis real + ROOT_PATH=$PREFIX =="
docker network create "$NET" >/dev/null
docker run -d --name smoke-redis --network "$NET" redis:7.4-alpine >/dev/null
for _ in $(seq 1 15); do
  if docker exec smoke-redis redis-cli ping 2>/dev/null | grep -q PONG; then break; fi
  sleep 1
done
docker exec smoke-redis redis-cli SET b3:trading:hours:open 10:00 >/dev/null
docker exec smoke-redis redis-cli SET b3:trading:hours:close 17:00 >/dev/null
docker run -d --name smoke-app --network "$NET" -p "$PORT:8000" \
  -e REDIS_URL_ENV=redis://smoke-redis:6379 -e ROOT_PATH="$PREFIX" "$IMAGE" >/dev/null
wait_ready
year=$(date -u +%Y)

log "-- forma strip_path=true (o Kong remove o prefixo) --"
expect GET /v1/health 200 application/json '"status":"healthy"'
expect GET /v1/hours 200 application/json '"open":"10:00","close":"17:00"'
expect GET /v1/hours/open 200 application/json '"time":"10:00"'
expect GET /v1/hours/close 200 application/json '"time":"17:00"'
expect GET /v1/is-trading-day 200 application/json '"is_trading_day"'
expect GET /v1/calendar-info 200 application/json '"exchange":"BVMF"'
expect GET "/v1/trading-days?start=${year}-01-02&end=${year}-01-31" 200 application/json "\"${year}-01-"
expect GET "/v1/trading-days?start=${year}-01-02&end=${year}-01-31&exclude=true" 200 application/json "\"${year}-01-"
expect GET "/v1/trading-days?start=${year}-01-31&end=${year}-01-02" 400 application/json '"Bad Request"'
expect GET "/v1/trading-days?start=${year}-13-01&end=${year}-01-31" 422 application/json
expect GET /openapi.json 200 application/json "\"servers\":[{\"url\":\"$PREFIX\"}]"
expect GET / 200 application/json '"version"'
expect GET /docs 200 text/html './static/swagger-ui-bundle.js'
expect GET /docs 200 text/html "url: './openapi.json'"
expect GET /redoc 200 text/html 'spec-url="./openapi.json"'
expect GET /static/swagger-ui.css 200 text/css
expect GET /static/swagger-ui-bundle.js 200 'application/javascript|text/javascript'
expect GET /static/redoc.standalone.js 200 'application/javascript|text/javascript'
expect GET /static/favicon.png 200 image/png
expect HEAD /static/swagger-ui.css 200 text/css

log "-- forma strip_path=false / --root-path (o prefixo vem em path) --"
expect GET "$PREFIX/" 200 application/json
expect GET "$PREFIX/docs" 200 text/html
expect GET "$PREFIX/redoc" 200 text/html
expect GET "$PREFIX/openapi.json" 200 application/json
expect GET "$PREFIX/static/swagger-ui.css" 200 text/css
expect GET "$PREFIX/v1/hours" 200 application/json

log "-- barra final: nunca um redirect para o host interno --"
expect GET /docs/ 404
expect GET /v1/hours/ 404
loc=$(curl -sSI --path-as-is "$BASE/docs/" | grep -i '^location:' || true)
if [ -n "$loc" ]; then log "FALHA /docs/ emitiu $loc"; fail=1; fi

log "-- negativos --"
expect GET /nao-existe 404
expect GET /static/nao-existe.css 404
expect GET /static/__init__.py 404
expect GET /static/%2e%2e/config.py 404
expect GET /static/..%2fconfig.py 404

log "-- HEALTHCHECK da imagem (intervalo 30 s) --"
status=""
for _ in $(seq 1 45); do
  status=$(docker inspect --format '{{.State.Health.Status}}' smoke-app)
  if [ "$status" = "healthy" ]; then break; fi
  sleep 2
done
if [ "$status" = "healthy" ]; then log "OK    HEALTHCHECK -> healthy"; else log "FALHA HEALTHCHECK -> $status"; fail=1; fi

if [ "$fail" -eq 0 ]; then log "Smoke test OK"; else log "Smoke test FALHOU"; exit 1; fi
