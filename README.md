<div align="center">
  <img src=".github/logo.svg" alt="B3 DateTime API Logo" width="400">
  
  <h1>B3 DateTime API</h1>
  
  <p>API REST em Python para consultar horários de operação e dias de negociação da B3 (Bolsa de Valores de São Paulo)</p>
</div>

## 📋 Descrição

A B3 DateTime API oferece endpoints para:
- Consultar horários de abertura e fechamento da bolsa (via Redis com cache local de 1h)
- Validar se determinada data é dia de negociação
- Listar dias de negociação ou não negociação em um período
- Verificar a saúde da aplicação e suas dependências

Utiliza o calendário BVMF (B3/Bovespa) do módulo `exchange_calendars` com suporte a dados a partir de 01/01/2006.

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
- **FastAPI**: Framework moderno e rápido com documentação automática OpenAPI/Redoc
- **Redis com Cache Local**: Fallback automático por até 1 hora se Redis estiver offline
- **Exchange Calendars**: Calendário oficial BVMF para validação de dias úteis
- **Timezone**: America/Sao_Paulo para todas as operações
- **Docker Multi-arch**: Suporte para linux/amd64 e linux/arm64
- **CI/CD**: Pipeline automático via GitHub Actions

## 🚀 Endpoints

### Horários de Operação

#### `GET /v1/hours`
Retorna horários de abertura e fechamento.

**Resposta:**
```json
{
  "open": "10:00",
  "close": "18:00"
}
```

**Exemplo:**
```bash
curl -H "apikey: YOUR_API_KEY" https://api.example.com/v1/hours
```

#### `GET /v1/hours/open`
Retorna apenas o horário de abertura.

**Resposta:**
```json
{
  "time": "10:00"
}
```

#### `GET /v1/hours/close`
Retorna apenas o horário de fechamento.

**Resposta:**
```json
{
  "time": "18:00"
}
```

### Dias de Negociação

#### `GET /v1/is-trading-day`
Verifica se hoje é dia de negociação na B3.

**Resposta:**
```json
{
  "date": "2024-01-15",
  "is_trading_day": true
}
```

**Exemplo:**
```bash
curl -H "apikey: YOUR_API_KEY" https://api.example.com/v1/is-trading-day
```

#### `GET /v1/trading-days`
Lista dias de negociação (ou não negociação) em um período.

**Parâmetros:**
- `start` (obrigatório): Data inicial no formato YYYY-MM-DD (>= 2006-01-01)
- `end` (obrigatório): Data final no formato YYYY-MM-DD
- `exclude` (opcional): `true` para listar dias SEM negociação, `false` (padrão) para listar dias COM negociação

**Resposta (exclude=false):**
```json
[
  "2024-01-02",
  "2024-01-03",
  "2024-01-04",
  "2024-01-05",
  "2024-01-08"
]
```

**Resposta (exclude=true):**
```json
[
  "2024-01-01",
  "2024-01-06",
  "2024-01-07"
]
```

**Exemplos:**
```bash
# Listar dias COM negociação
curl -H "apikey: YOUR_API_KEY" \
  "https://api.example.com/v1/trading-days?start=2024-01-01&end=2024-01-31"

# Listar dias SEM negociação (feriados e finais de semana)
curl -H "apikey: YOUR_API_KEY" \
  "https://api.example.com/v1/trading-days?start=2024-01-01&end=2024-01-31&exclude=true"
```

### Health Check

#### `GET /v1/health`
Verifica a saúde da API e suas dependências.

**Resposta (healthy):**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00-03:00",
  "redis_status": "connected",
  "cache": {
    "redis_connected": true,
    "open_cache_age_seconds": 120,
    "close_cache_age_seconds": 120,
    "cache_ttl_seconds": 3600
  }
}
```

**Resposta (degraded - Redis offline, usando cache):**
```json
{
  "status": "degraded",
  "timestamp": "2024-01-15T10:30:00-03:00",
  "redis_status": "disconnected",
  "cache": {
    "redis_connected": false,
    "open_cache_age_seconds": 1800,
    "close_cache_age_seconds": 1800,
    "cache_ttl_seconds": 3600
  }
}
```

### Informações da API

#### `GET /`
Retorna informações básicas sobre a API.

**Resposta:**
```json
{
  "name": "B3 DateTime API",
  "version": "1.0.0",
  "description": "API para consultar horários e dias de operação da B3",
  "docs": {
    "swagger": "/docs",
    "redoc": "/redoc",
    "openapi": "/openapi.json"
  },
  "endpoints": {
    "hours": {
      "all": "/v1/hours",
      "open": "/v1/hours/open",
      "close": "/v1/hours/close"
    },
    "dates": {
      "is_trading_day": "/v1/is-trading-day",
      "trading_days": "/v1/trading-days?start=YYYY-MM-DD&end=YYYY-MM-DD&exclude=false"
    },
    "health": "/v1/health"
  },
  "authentication": {
    "type": "API Key",
    "header": "apikey",
    "managed_by": "Kong Gateway"
  }
}
```

## 🔐 Autenticação

Todas as requisições devem incluir o header `apikey` com uma chave válida:

```bash
curl -H "apikey: YOUR_API_KEY" https://api.example.com/v1/hours
```

A autenticação é gerenciada externamente pelo **Kong Gateway**. A API não valida as chaves diretamente.

## ⚙️ Variáveis de Ambiente

| Variável | Descrição | Padrão | Obrigatório |
|----------|-----------|--------|-------------|
| `REDIS_URL_ENV` | URL de conexão do Redis | `redis://localhost:6379` | Sim |
| `REDIS_KEY_OPEN` | Chave Redis para horário de abertura | `b3:trading:hours:open` | Sim |
| `REDIS_KEY_CLOSE` | Chave Redis para horário de fechamento | `b3:trading:hours:close` | Sim |

**Exemplo de configuração (.env):**
```env
REDIS_URL_ENV=redis://localhost:6379
REDIS_KEY_OPEN=b3:trading:hours:open
REDIS_KEY_CLOSE=b3:trading:hours:close
```

## 💾 Cache e Fallback

A API implementa um sistema de cache inteligente:

1. **Tentativa primária**: Busca valores diretamente do Redis
2. **Cache local**: Se Redis falhar, usa cache em memória (válido por 1 hora)
3. **Erro 503**: Se Redis indisponível por mais de 1 hora, retorna erro

**Benefícios:**
- Alta disponibilidade durante instabilidades temporárias do Redis
- Redução de latência com cache local
- Degradação controlada do serviço

## 🐳 Docker

### Build Local

```bash
docker build -t b3datetime:latest .
```

### Executar Container

```bash
docker run -d \
  -p 8000:8000 \
  -e REDIS_URL_ENV=redis://redis-host:6379 \
  -e REDIS_KEY_OPEN=b3:trading:hours:open \
  -e REDIS_KEY_CLOSE=b3:trading:hours:close \
  --name b3datetime \
  b3datetime:latest
```

### Docker Compose

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  
  b3datetime:
    build: .
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL_ENV=redis://redis:6379
      - REDIS_KEY_OPEN=b3:trading:hours:open
      - REDIS_KEY_CLOSE=b3:trading:hours:close
    depends_on:
      - redis
```

## 💻 Desenvolvimento Local

### Pré-requisitos

- Python 3.11+
- Redis (local ou remoto)

### Instalação

1. Clone o repositório:
```bash
git clone https://github.com/rlquilez/b3datetime.git
cd b3datetime
```

2. Crie um ambiente virtual:
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# ou
venv\Scripts\activate  # Windows
```

3. Instale as dependências:
```bash
pip install -r requirements.txt
```

4. Configure as variáveis de ambiente:
```bash
cp .env.example .env
# Edite .env com suas configurações
```

5. Inicie o servidor:
```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

6. Acesse a documentação:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

## 📊 Preparando Redis

Para que a API funcione corretamente, configure as chaves no Redis:

```bash
# Conectar ao Redis
redis-cli

# Configurar horários
SET b3:trading:hours:open "10:00"
SET b3:trading:hours:close "18:00"

# Verificar
GET b3:trading:hours:open
GET b3:trading:hours:close
```

## 🔧 Tecnologias

- **[FastAPI](https://fastapi.tiangolo.com/)** - Framework web moderno e rápido
- **[Uvicorn](https://www.uvicorn.org/)** - Servidor ASGI de alta performance
- **[Redis](https://redis.io/)** - Armazenamento de horários
- **[exchange_calendars](https://github.com/gerrymanoim/exchange_calendars)** - Calendários de bolsas de valores
- **[Pydantic](https://pydantic-docs.helpmanual.io/)** - Validação de dados
- **[Docker](https://www.docker.com/)** - Containerização
- **[GitHub Actions](https://github.com/features/actions)** - CI/CD

## 📝 Limitações e Considerações

- **Data mínima**: Calendário BVMF disponível a partir de **01/01/2006**
- **Timezone**: Todas as operações utilizam **America/Sao_Paulo**
- **Cache TTL**: Cache local expira após **1 hora (3600 segundos)**
- **Sem limite de range**: Endpoint `/v1/trading-days` aceita qualquer range desde que start >= 2006-01-01
- **Horários estáticos**: Horários obtidos do Redis são considerados estáticos (não considera pregões especiais)

## 🚀 CI/CD

A aplicação possui pipeline automático via GitHub Actions:

- **Trigger**: Push nas branches `main` ou `proxima`
- **Build**: Imagem Docker multi-arquitetura (linux/amd64, linux/arm64)
- **Push**: Enviado para registry configurado nos secrets
- **Cache**: Utiliza GitHub Actions cache para otimização

**Secrets necessários:**
- `GIT_REGISTRY` - URL do registry (ex: ghcr.io)
- `GIT_OWNER` - Owner/organização
- `GIT_REGISTRY_USER` - Usuário do registry
- `GIT_REGISTRY_PASSWORD` - Token/senha do registry
## 📄 Licença

Este projeto está sob a licença MIT - veja o arquivo [LICENSE](LICENSE) para mais detalhes.

Você é livre para usar, copiar, modificar e distribuir este software para qualquer finalidade, incluindo uso comercial, desde que mantenha o aviso de copyright e a licença.

## 👤 Autor

Rodrigo Quilez (@rlquilez)

## 🤝 Contribuindo

Contribuições são bem-vindas! Sinta-se à vontade para abrir issues e pull requests.

## 📚 Documentação Adicional

- [Documentação FastAPI](https://fastapi.tiangolo.com/)
- [Exchange Calendars](https://github.com/gerrymanoim/exchange_calendars)
- [Redis Python Client](https://redis-py.readthedocs.io/)
- [Kong Gateway](https://docs.konghq.com/)
