"""
Router para endpoints de dias de negociação da B3.
"""
from datetime import date, datetime
from typing import List, Optional

import exchange_calendars as xcals
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.config import settings, TZ, get_current_datetime, get_min_allowed_date

router = APIRouter(
    prefix="/v1",
    tags=["Dias de Negociação"]
)

# Inicializa o calendário BVMF (B3)
try:
    bvmf_calendar = xcals.get_calendar(settings.exchange_name)
except Exception as e:
    raise RuntimeError(f"Erro ao carregar calendário {settings.exchange_name}: {e}")


class TradingDayResponse(BaseModel):
    """Modelo para resposta de validação de dia de negociação."""
    date: str = Field(..., description="Data verificada no formato YYYY-MM-DD", example="2024-01-15")
    is_trading_day: bool = Field(..., description="Se é um dia de negociação na B3", example=True)


@router.get(
    "/is-trading-day",
    response_model=TradingDayResponse,
    summary="Verificar se hoje é dia de negociação",
    description="""
    Verifica se o dia atual é um dia de negociação na B3.
    
    Utiliza o calendário BVMF (B3/Bovespa) do exchange_calendars para determinar
    se a bolsa opera no dia atual, considerando feriados e finais de semana.
    
    O "dia atual" é determinado usando o timezone America/Sao_Paulo.
    
    **Autenticação**: Requer header `apikey` configurado no Kong Gateway.
    """,
    responses={
        200: {
            "description": "Verificação realizada com sucesso",
            "content": {
                "application/json": {
                    "examples": {
                        "trading_day": {
                            "summary": "Dia de negociação",
                            "value": {
                                "date": "2024-01-15",
                                "is_trading_day": True
                            }
                        },
                        "non_trading_day": {
                            "summary": "Não é dia de negociação",
                            "value": {
                                "date": "2024-01-20",
                                "is_trading_day": False
                            }
                        }
                    }
                }
            }
        }
    }
)
async def is_trading_day():
    """Verifica se hoje é dia de negociação na B3."""
    today = get_current_datetime().date()
    is_open = bvmf_calendar.is_session(today)
    
    return TradingDayResponse(
        date=today.isoformat(),
        is_trading_day=is_open
    )


@router.get(
    "/trading-days",
    response_model=List[str],
    summary="Listar dias de negociação em um período",
    description="""
    Retorna uma lista de dias de negociação (ou não negociação) em um período específico.
    
    Utiliza o calendário BVMF (B3/Bovespa) do exchange_calendars.
    
    **Parâmetros**:
    - `start`: Data inicial no formato YYYY-MM-DD (obrigatório, >= 2006-01-01)
    - `end`: Data final no formato YYYY-MM-DD (obrigatório, >= start)
    - `exclude`: Se True, retorna dias SEM negociação; se False, retorna dias COM negociação (padrão: False)
    
    **Restrições**:
    - Data inicial deve ser >= 2006-01-01
    - Data final deve ser >= data inicial
    - Sem limite de dias no range
    
    **Autenticação**: Requer header `apikey` configurado no Kong Gateway.
    """,
    responses={
        200: {
            "description": "Lista de datas obtida com sucesso",
            "content": {
                "application/json": {
                    "examples": {
                        "trading_days": {
                            "summary": "Dias de negociação",
                            "value": [
                                "2024-01-02",
                                "2024-01-03",
                                "2024-01-04",
                                "2024-01-05",
                                "2024-01-08"
                            ]
                        },
                        "non_trading_days": {
                            "summary": "Dias sem negociação (exclude=true)",
                            "value": [
                                "2024-01-01",
                                "2024-01-06",
                                "2024-01-07"
                            ]
                        }
                    }
                }
            }
        },
        400: {
            "description": "Parâmetros inválidos",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Data inicial deve ser >= 2006-01-01"
                    }
                }
            }
        }
    }
)
async def get_trading_days(
    start: str = Query(
        ...,
        description="Data inicial no formato YYYY-MM-DD (>= 2006-01-01)",
        example="2024-01-01",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    end: str = Query(
        ...,
        description="Data final no formato YYYY-MM-DD (>= start)",
        example="2024-01-31",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    exclude: bool = Query(
        False,
        description="Se True, retorna dias SEM negociação; se False, retorna dias COM negociação"
    )
):
    """
    Lista dias de negociação (ou não negociação) em um período.
    """
    # Valida e converte datas
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Formato de data inválido: {e}. Use YYYY-MM-DD"
        )
    
    # Valida data mínima (2006-01-01)
    min_date = get_min_allowed_date().date()
    if start_date < min_date:
        raise HTTPException(
            status_code=400,
            detail=f"Data inicial deve ser >= {min_date.isoformat()}"
        )
    
    # Valida que end >= start
    if end_date < start_date:
        raise HTTPException(
            status_code=400,
            detail="Data final deve ser >= data inicial"
        )
    
    # Obtém schedule do calendário
    try:
        schedule = bvmf_calendar.sessions_in_range(start_date, end_date)
        trading_days = [day.date() for day in schedule]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao consultar calendário: {e}"
        )
    
    # Se exclude=True, retorna dias que NÃO são de negociação
    if exclude:
        # Gera todas as datas no range
        all_days = []
        current = start_date
        while current <= end_date:
            all_days.append(current)
            current = date.fromordinal(current.toordinal() + 1)
        
        # Filtra dias que não são de negociação
        non_trading_days = [
            day for day in all_days if day not in trading_days
        ]
        return [day.isoformat() for day in non_trading_days]
    
    # Retorna dias de negociação
    return [day.isoformat() for day in trading_days]
