"""
B3 DateTime API - API para consultar horários e dias de operação da B3.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.routers import hours, dates, health

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação."""
    logger.info("Iniciando B3 DateTime API...")
    logger.info(f"Timezone configurado: {settings.timezone}")
    logger.info(f"Exchange: {settings.exchange_name}")
    logger.info(f"Redis URL: {settings.redis_url}")
    logger.info(f"Cache TTL: {settings.cache_ttl_seconds}s")
    yield
    logger.info("Encerrando B3 DateTime API...")


# Criar aplicação FastAPI
app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    contact={
        "name": "B3 DateTime API",
        "url": "https://github.com/rlquilez/b3datetime"
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT"
    }
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar routers
app.include_router(hours.router)
app.include_router(dates.router)
app.include_router(health.router)


@app.get(
    "/",
    tags=["Root"],
    summary="Informações da API",
    description="Retorna informações básicas sobre a API."
)
async def root():
    """Endpoint raiz com informações da API."""
    return {
        "name": settings.api_title,
        "version": settings.api_version,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
