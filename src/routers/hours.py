"""
Router para endpoints de horários de operação da B3.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.services.redis_service import redis_service

router = APIRouter(
    prefix="/v1/hours",
    tags=["Horários de Operação"]
)


class TradingHours(BaseModel):
    """Modelo para horários de abertura e fechamento."""
    open: str = Field(..., description="Horário de abertura no formato HH:MM", example="10:00")
    close: str = Field(..., description="Horário de fechamento no formato HH:MM", example="18:00")


class TradingTime(BaseModel):
    """Modelo para horário único."""
    time: str = Field(..., description="Horário no formato HH:MM", example="10:00")


@router.get(
    "",
    response_model=TradingHours,
    summary="Obter horários de abertura e fechamento",
    description="""
    Retorna os horários de abertura e fechamento da B3.
    
    Os horários são obtidos do Redis e mantidos em cache local por até 1 hora.
    Se o Redis estiver indisponível por mais de 1 hora, retorna erro 503.
    
    **Autenticação**: Requer header `apikey` configurado no Kong Gateway.
    """,
    responses={
        200: {
            "description": "Horários obtidos com sucesso",
            "content": {
                "application/json": {
                    "example": {
                        "open": "10:00",
                        "close": "18:00"
                    }
                }
            }
        },
        503: {
            "description": "Redis indisponível e cache expirado",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "Service Unavailable",
                            "message": "Redis indisponível há mais de 3600s",
                            "cache_age_seconds": 3700,
                            "key": "b3:trading:hours:open"
                        }
                    }
                }
            }
        }
    }
)
async def get_trading_hours():
    """Retorna horários de abertura e fechamento."""
    open_time = redis_service.get_open_time()
    close_time = redis_service.get_close_time()
    
    return TradingHours(open=open_time, close=close_time)


@router.get(
    "/open",
    response_model=TradingTime,
    summary="Obter horário de abertura",
    description="""
    Retorna apenas o horário de abertura da B3.
    
    Os horários são obtidos do Redis e mantidos em cache local por até 1 hora.
    
    **Autenticação**: Requer header `apikey` configurado no Kong Gateway.
    """,
    responses={
        200: {
            "description": "Horário de abertura obtido com sucesso",
            "content": {
                "application/json": {
                    "example": {
                        "time": "10:00"
                    }
                }
            }
        },
        503: {
            "description": "Redis indisponível e cache expirado"
        }
    }
)
async def get_open_time():
    """Retorna horário de abertura."""
    open_time = redis_service.get_open_time()
    return TradingTime(time=open_time)


@router.get(
    "/close",
    response_model=TradingTime,
    summary="Obter horário de fechamento",
    description="""
    Retorna apenas o horário de fechamento da B3.
    
    Os horários são obtidos do Redis e mantidos em cache local por até 1 hora.
    
    **Autenticação**: Requer header `apikey` configurado no Kong Gateway.
    """,
    responses={
        200: {
            "description": "Horário de fechamento obtido com sucesso",
            "content": {
                "application/json": {
                    "example": {
                        "time": "18:00"
                    }
                }
            }
        },
        503: {
            "description": "Redis indisponível e cache expirado"
        }
    }
)
async def get_close_time():
    """Retorna horário de fechamento."""
    close_time = redis_service.get_close_time()
    return TradingTime(time=close_time)
