"""
Router para endpoint de health check.
"""
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.services.redis_service import redis_service
from src.config import TZ, get_current_datetime

router = APIRouter(
    prefix="/v1",
    tags=["Health Check"]
)


class HealthResponse(BaseModel):
    """Modelo para resposta do health check."""
    status: str = Field(..., description="Status geral da API", example="healthy")
    timestamp: str = Field(..., description="Timestamp do health check no formato ISO 8601", example="2024-01-15T10:30:00-03:00")
    redis_status: str = Field(..., description="Status da conexão Redis", example="connected")
    cache: dict = Field(..., description="Informações sobre o cache local")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Verificar saúde da API",
    description="""
    Retorna informações sobre o status da API e suas dependências.
    
    **Informações retornadas**:
    - Status geral da API (healthy/degraded/unhealthy)
    - Timestamp do health check
    - Status da conexão Redis (connected/disconnected)
    - Informações sobre o cache local:
      - Conexão com Redis
      - Idade do cache para horário de abertura (segundos)
      - Idade do cache para horário de fechamento (segundos)
      - TTL configurado do cache (segundos)
    
    **Status**:
    - `healthy`: API operando normalmente, Redis conectado
    - `degraded`: Redis desconectado mas cache local disponível
    - `unhealthy`: Redis desconectado e sem cache local
    
    **Autenticação**: Requer header `apikey` configurado no Kong Gateway.
    """,
    responses={
        200: {
            "description": "Health check realizado com sucesso",
            "content": {
                "application/json": {
                    "examples": {
                        "healthy": {
                            "summary": "Sistema saudável",
                            "value": {
                                "status": "healthy",
                                "timestamp": "2024-01-15T10:30:00-03:00",
                                "redis_status": "connected",
                                "cache": {
                                    "redis_connected": True,
                                    "open_cache_age_seconds": 120,
                                    "close_cache_age_seconds": 120,
                                    "cache_ttl_seconds": 3600
                                }
                            }
                        },
                        "degraded": {
                            "summary": "Sistema degradado (Redis offline, usando cache)",
                            "value": {
                                "status": "degraded",
                                "timestamp": "2024-01-15T10:30:00-03:00",
                                "redis_status": "disconnected",
                                "cache": {
                                    "redis_connected": False,
                                    "open_cache_age_seconds": 1800,
                                    "close_cache_age_seconds": 1800,
                                    "cache_ttl_seconds": 3600
                                }
                            }
                        },
                        "unhealthy": {
                            "summary": "Sistema não saudável (Redis offline, sem cache)",
                            "value": {
                                "status": "unhealthy",
                                "timestamp": "2024-01-15T10:30:00-03:00",
                                "redis_status": "disconnected",
                                "cache": {
                                    "redis_connected": False,
                                    "open_cache_age_seconds": None,
                                    "close_cache_age_seconds": None,
                                    "cache_ttl_seconds": 3600
                                }
                            }
                        }
                    }
                }
            }
        }
    }
)
async def health_check():
    """Retorna informações de saúde da API."""
    cache_status = redis_service.get_cache_status()
    redis_connected = cache_status["redis_connected"]
    
    # Determina status geral
    if redis_connected:
        status = "healthy"
        redis_status = "connected"
    elif cache_status["open_cache_age_seconds"] is not None:
        status = "degraded"
        redis_status = "disconnected"
    else:
        status = "unhealthy"
        redis_status = "disconnected"
    
    return HealthResponse(
        status=status,
        timestamp=get_current_datetime().isoformat(),
        redis_status=redis_status,
        cache=cache_status
    )
