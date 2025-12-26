"""
Configurações da aplicação B3 DateTime API.
Carrega variáveis de ambiente e define constantes.
"""
import os
from datetime import datetime
from typing import Optional

import pytz
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configurações da aplicação carregadas de variáveis de ambiente."""
    
    # Configurações Redis
    redis_url: str = os.getenv("REDIS_URL_ENV", "redis://localhost:6379")
    redis_key_open: str = os.getenv("REDIS_KEY_OPEN", "b3:trading:hours:open")
    redis_key_close: str = os.getenv("REDIS_KEY_CLOSE", "b3:trading:hours:close")
    
    # Configurações de Cache
    cache_ttl_seconds: int = 3600  # 1 hora
    
    # Configurações de Timezone
    timezone: str = "America/Sao_Paulo"
    
    # Configurações de Exchange Calendar
    exchange_name: str = "BVMF"  # B3/Bovespa
    min_date_year: int = 2006  # Data mínima permitida: 01/01/2006
    
    # Configurações da API
    api_title: str = "B3 DateTime API"
    api_description: str = """
    API para consultar horários de operação e dias de negociação da B3 (Bolsa de Valores de São Paulo).
    
    ## Autenticação
    
    Todas as requisições devem incluir o header `apikey` com uma chave válida gerenciada pelo Kong Gateway.
    
    ## Características
    
    * **Horários de Operação**: Consulte horários de abertura e fechamento via Redis (cache local de 1h)
    * **Dias de Negociação**: Valide se um dia é útil na B3 usando exchange_calendars
    * **Dados Históricos**: Suporte para datas a partir de 01/01/2006
    * **Timezone**: Todos os horários e datas utilizam timezone America/Sao_Paulo
    """
    api_version: str = "1.0.0"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Instância global das configurações
settings = Settings()

# Timezone configurado
TZ = pytz.timezone(settings.timezone)


def get_current_datetime() -> datetime:
    """Retorna a data e hora atual no timezone configurado."""
    return datetime.now(TZ)


def get_min_allowed_date() -> datetime:
    """Retorna a data mínima permitida (01/01/2006)."""
    return TZ.localize(datetime(settings.min_date_year, 1, 1))
