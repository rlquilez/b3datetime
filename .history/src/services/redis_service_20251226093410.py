"""
Serviço para gerenciar conexão com Redis e cache local.
Implementa cache em memória com TTL de 1 hora para fallback.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging

import redis
from fastapi import HTTPException

from src.config import settings, TZ

logger = logging.getLogger(__name__)


class RedisCache:
    """Cache local para armazenar valores com timestamp."""
    
    def __init__(self):
        self.cache: Dict[str, tuple[str, datetime]] = {}
    
    def set(self, key: str, value: str) -> None:
        """Armazena valor no cache com timestamp atual."""
        self.cache[key] = (value, datetime.now(TZ))
    
    def get(self, key: str) -> Optional[tuple[str, datetime]]:
        """Retorna tupla (valor, timestamp) do cache ou None."""
        return self.cache.get(key)
    
    def is_expired(self, key: str, ttl_seconds: int) -> bool:
        """Verifica se o cache expirou baseado no TTL."""
        cached = self.get(key)
        if not cached:
            return True
        
        _, timestamp = cached
        age = datetime.now(TZ) - timestamp
        return age.total_seconds() > ttl_seconds
    
    def get_age_seconds(self, key: str) -> Optional[float]:
        """Retorna a idade do cache em segundos ou None."""
        cached = self.get(key)
        if not cached:
            return None
        
        _, timestamp = cached
        age = datetime.now(TZ) - timestamp
        return age.total_seconds()


class RedisService:
    """Serviço para gerenciar conexão Redis com cache local de fallback."""
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.local_cache = RedisCache()
        self._initialize_connection()
    
    def _initialize_connection(self) -> None:
        """Inicializa conexão com Redis."""
        try:
            self.redis_client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Testa conexão
            self.redis_client.ping()
            logger.info(f"Conexão com Redis estabelecida: {settings.redis_url}")
        except Exception as e:
            logger.error(f"Erro ao conectar com Redis: {e}")
            self.redis_client = None
    
    def _get_from_redis(self, key: str) -> Optional[str]:
        """Busca valor diretamente do Redis."""
        if not self.redis_client:
            return None
        
        try:
            value = self.redis_client.get(key)
            if value:
                # Atualiza cache local
                self.local_cache.set(key, value)
                logger.debug(f"Valor obtido do Redis para chave '{key}': {value}")
            return value
        except Exception as e:
            logger.error(f"Erro ao buscar chave '{key}' no Redis: {e}")
            return None
    
    def get_value(self, key: str) -> str:
        """
        Busca valor do Redis com fallback para cache local.
        
        Estratégia:
        1. Tenta buscar do Redis
        2. Se falhar, usa cache local se disponível e não expirado (< 1h)
        3. Se cache expirou (> 1h), retorna erro 503
        
        Args:
            key: Chave do Redis
            
        Returns:
            Valor armazenado
            
        Raises:
            HTTPException: 503 se Redis indisponível e cache expirado
            HTTPException: 404 se chave não existe
        """
        # Tenta buscar do Redis
        value = self._get_from_redis(key)
        
        if value:
            return value
        
        # Redis falhou, verifica cache local
        cached = self.local_cache.get(key)
        
        if not cached:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "Service Unavailable",
                    "message": "Redis indisponível e nenhum valor em cache local",
                    "key": key
                }
            )
        
        cached_value, cached_timestamp = cached
        cache_age = self.local_cache.get_age_seconds(key)
        
        # Verifica se cache expirou (> 1 hora)
        if cache_age and cache_age > settings.cache_ttl_seconds:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "Service Unavailable",
                    "message": f"Redis indisponível há mais de {settings.cache_ttl_seconds}s",
                    "cache_age_seconds": int(cache_age),
                    "key": key
                }
            )
        
        # Cache válido, retorna valor
        logger.warning(
            f"Usando cache local para chave '{key}' (idade: {int(cache_age)}s)"
        )
        return cached_value
    
    def get_open_time(self) -> str:
        """Retorna horário de abertura da B3."""
        return self.get_value(settings.redis_key_open)
    
    def get_close_time(self) -> str:
        """Retorna horário de fechamento da B3."""
        return self.get_value(settings.redis_key_close)
    
    def is_connected(self) -> bool:
        """Verifica se Redis está conectado."""
        if not self.redis_client:
            return False
        
        try:
            self.redis_client.ping()
            return True
        except Exception:
            return False
    
    def get_cache_status(self) -> dict:
        """Retorna status do cache local."""
        open_age = self.local_cache.get_age_seconds(settings.redis_key_open)
        close_age = self.local_cache.get_age_seconds(settings.redis_key_close)
        
        return {
            "redis_connected": self.is_connected(),
            "open_cache_age_seconds": int(open_age) if open_age else None,
            "close_cache_age_seconds": int(close_age) if close_age else None,
            "cache_ttl_seconds": settings.cache_ttl_seconds
        }


# Instância global do serviço
redis_service = RedisService()
