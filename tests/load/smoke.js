// Teste de carga de fumaça (k6) do job "Performance · k6".
//
// Alvo: a imagem verificada pelo CI, atrás de tests/stack/compose.yaml (Redis semeado,
// ROOT_PATH). Não é benchmark: a pergunta é "a API continua respondendo certo e rápido
// sob carga concorrente?". Limiares generosos para o runner compartilhado do GitHub, mas
// que reprovam as regressões que importam — uma chamada bloqueante no event loop, um
// algoritmo quadrático de volta em /v1/trading-days, um 5xx sob concorrência.
//
// Três cenários simultâneos, depois de medir a linha de base do health ocioso:
//   mix    — todas as operações do contrato, com taxa constante;
//   caro   — /v1/trading-days no span máximo, com exclude=true (o pior caso);
//   health — /v1/health durante os dois acima: o health sob carga não pode ficar mais
//            que LIMITE_RELATIVO vezes mais lento que o ocioso (piso de PISO_MS).
//
// Racional e decisões: tests/README.md, seção Performance.
import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://app:8000/b3datetime';
const DURACAO = __ENV.DURACAO || '30s';

// Toda operação do contrato (tests/contract/openapi.json) tem uma entrada aqui;
// tests/unit/test_scripts_k6_resumo.py confere. `consulta` recebe a janela do
// calendário (de /v1/calendar-info) e devolve a query string.
const ENDPOINTS = {
  raiz: { caminho: '/' },
  horarios: { caminho: '/v1/hours' },
  abertura: { caminho: '/v1/hours/open' },
  fechamento: { caminho: '/v1/hours/close' },
  hoje: { caminho: '/v1/is-trading-day' },
  calendario: { caminho: '/v1/calendar-info' },
  periodo: { caminho: '/v1/trading-days', consulta: (j) => `start=${j.ultimoMes}&end=${j.fim}` },
  health: { caminho: '/v1/health' },
};

// p95 máximo por endpoint, em ms. Localmente cada um responde em 2–8 ms.
const P95_BARATO_MS = 250;
const P95_CARO_MS = 750;
const LIMITE_RELATIVO = 5;
const PISO_MS = 10;
const AMOSTRAS_OCIOSAS = 50;

const healthRelativo = new Trend('health_sob_carga_relativo');

const limiares = {
  http_req_failed: ['rate==0'],
  checks: ['rate==1'],
  // Taxa constante: iteração descartada significa que a API não deu conta da vazão.
  dropped_iterations: ['count==0'],
  health_sob_carga_relativo: [`p(95)<${LIMITE_RELATIVO}`],
  'http_req_duration{endpoint:caro}': [`p(95)<${P95_CARO_MS}`],
};
for (const nome of Object.keys(ENDPOINTS)) {
  limiares[`http_req_duration{endpoint:${nome}}`] = [`p(95)<${P95_BARATO_MS}`];
}

const cenario = (exec, rate) => ({
  executor: 'constant-arrival-rate',
  exec,
  rate,
  timeUnit: '1s',
  duration: DURACAO,
  preAllocatedVUs: rate,
  maxVUs: rate * 4,
});

export const options = {
  scenarios: {
    mix: cenario('mix', 10),
    caro: cenario('caro', 5),
    health: cenario('health', 10),
  },
  thresholds: limiares,
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
};

function isoMaisDias(iso, dias) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

function percentil95(valores) {
  const ordenados = [...valores].sort((a, b) => a - b);
  return ordenados[Math.ceil(0.95 * ordenados.length) - 1];
}

export function setup() {
  const info = http.get(`${BASE}/v1/calendar-info`, { tags: { endpoint: 'preparacao' } });
  if (info.status !== 200) {
    throw new Error(`calendar-info respondeu ${info.status}: a stack não está pronta`);
  }
  const c = info.json();
  // O pior caso: o span máximo aceito, a partir do início da janela.
  const fimCaro = isoMaisDias(c.coverage_start, c.max_range_days);
  const janela = {
    inicio: c.coverage_start,
    fim: c.coverage_end,
    fimCaro: fimCaro < c.coverage_end ? fimCaro : c.coverage_end,
    ultimoMes: isoMaisDias(c.coverage_end, -30),
  };

  // Linha de base: o health ocioso, em série, antes de qualquer carga.
  const duracoes = [];
  for (let i = 0; i < AMOSTRAS_OCIOSAS; i += 1) {
    duracoes.push(http.get(`${BASE}/v1/health`, { tags: { endpoint: 'linha_de_base' } }).timings.duration);
  }
  return { janela, healthOcioso: percentil95(duracoes) };
}

function pedir(nome, url) {
  const r = http.get(url, { tags: { endpoint: nome } });
  check(r, {
    [`${nome}: 200`]: (res) => res.status === 200,
    [`${nome}: JSON`]: (res) => (res.headers['Content-Type'] || '').startsWith('application/json'),
  });
  return r;
}

export function mix(dados) {
  for (const [nome, ep] of Object.entries(ENDPOINTS)) {
    const consulta = ep.consulta ? `?${ep.consulta(dados.janela)}` : '';
    pedir(nome, `${BASE}${ep.caminho}${consulta}`);
  }
}

export function caro(dados) {
  const j = dados.janela;
  pedir('caro', `${BASE}/v1/trading-days?start=${j.inicio}&end=${j.fimCaro}&exclude=true`);
}

export function health(dados) {
  const r = pedir('health', `${BASE}/v1/health`);
  healthRelativo.add(r.timings.duration / Math.max(dados.healthOcioso, PISO_MS));
}
