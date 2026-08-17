"""Acesso ao Redis com cache local de fallback.

Pontos de projeto que existem por causa de defeitos concretos:

* O cliente é ``redis.asyncio``. O cliente síncrono chamado de ``async def`` congelava
  o event loop inteiro por até ``socket_timeout`` a cada requisição.
* ``__init__`` não faz I/O, e o cliente **nunca** é anulado. A versão anterior
  descartava o cliente quando o ping inicial falhava, e como a inicialização só
  acontecia no construtor, a API respondia 503 para sempre mesmo depois de o Redis
  voltar — só um restart resolvia.
* ``get_trading_hours`` usa um único ``MGET``. Duas leituras sequenciais, além de
  dobrarem a latência, não eram atômicas: um escritor concorrente podia produzir uma
  resposta com o ``open`` de ontem e o ``close`` de hoje.
* Ausência de chave e indisponibilidade do Redis são causas distintas, e produzem
  status HTTP distintos (404 e 503). Colapsar as duas fazia a API afirmar "Redis
  indisponível" quando o Redis estava no ar e faltava apenas um ``SET``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from src.config import Settings, get_current_datetime

if TYPE_CHECKING:  # pragma: no cover
    from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NowFn = Callable[[], datetime]
ClientFactory = Callable[[], "aioredis.Redis"]


class KeyNotFoundError(LookupError):
    """A chave não existe no Redis, que está disponível."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Chave '{key}' não encontrada no Redis")


class RedisUnavailableError(RuntimeError):
    """O Redis está indisponível e não há valor utilizável em cache."""

    def __init__(
        self, message: str, *, key: str | None = None, cache_age: float | None = None
    ) -> None:
        self.key = key
        self.cache_age = cache_age
        super().__init__(message)


class RedisCache:
    """Cache em memória com timestamp por chave."""

    def __init__(self, now_fn: NowFn | None = None) -> None:
        self._entries: dict[str, tuple[str, datetime]] = {}
        self._now: NowFn = now_fn or get_current_datetime

    def set(self, key: str, value: str) -> None:
        self._entries[key] = (value, self._now())

    def get(self, key: str) -> tuple[str, datetime] | None:
        return self._entries.get(key)

    def get_value(self, key: str) -> str | None:
        entry = self._entries.get(key)
        return entry[0] if entry is not None else None

    def get_age_seconds(self, key: str) -> float | None:
        """Idade da entrada em segundos, ou ``None`` se a chave não está em cache.

        ``None`` significa "não há cache"; ``0.0`` significa "cache recém-escrito".
        Confundir os dois — o que acontecia com ``int(age) if age else None`` — fazia
        um cache recém-populado ser reportado como ausente.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        return (self._now() - entry[1]).total_seconds()

    def is_expired(self, key: str, ttl_seconds: int) -> bool:
        age = self.get_age_seconds(key)
        if age is None:
            return True
        return age > ttl_seconds

    def clear(self) -> None:
        self._entries.clear()


class RedisService:
    """Leitura dos horários de negociação, com fallback para cache local."""

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: ClientFactory | None = None,
        now_fn: NowFn | None = None,
    ) -> None:
        self._settings = settings
        self._now: NowFn = now_fn or (lambda: get_current_datetime(settings.tz))
        self._client_factory: ClientFactory = client_factory or self._default_client_factory
        self._client: aioredis.Redis | None = None
        self._last_connect_attempt: datetime | None = None
        self._connect_lock = asyncio.Lock()
        self.local_cache = RedisCache(now_fn=self._now)

    # --- ciclo de vida -----------------------------------------------------

    def _default_client_factory(self) -> aioredis.Redis:
        timeout = self._settings.redis_socket_timeout_seconds
        return aioredis.from_url(
            self._settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )

    async def connect(self) -> None:
        """Tenta estabelecer a conexão. Falha é logada, não propagada."""
        await self._ensure_client()

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            await client.aclose()
        except (RedisError, OSError) as exc:
            logger.warning("Erro ao fechar a conexão com o Redis: %s", exc)

    async def _ensure_client(self) -> aioredis.Redis | None:
        """Devolve um cliente utilizável, reconectando com throttle quando preciso."""
        if self._client is not None:
            return self._client

        async with self._connect_lock:
            if self._client is not None:
                return self._client

            # Throttle: sem isso, cada requisição com o Redis fora dispararia uma
            # tentativa de conexão, com o custo de socket_connect_timeout embutido.
            now = self._now()
            interval = self._settings.redis_reconnect_interval_seconds
            if self._last_connect_attempt is not None:
                elapsed = (now - self._last_connect_attempt).total_seconds()
                if elapsed < interval:
                    return None
            self._last_connect_attempt = now

            try:
                client = self._client_factory()
                await client.ping()
            except (RedisError, OSError) as exc:
                # warning e não exception: com o Redis fora isto se repete a cada
                # intervalo de reconexão, e o traceback completo seria só ruído.
                logger.warning(
                    "Falha ao conectar no Redis (%s): %s", self._settings.redis_url_safe, exc
                )
                return None

            logger.info("Conexão com o Redis estabelecida: %s", self._settings.redis_url_safe)
            self._client = client
            return client

    # --- leitura -----------------------------------------------------------

    async def _fetch(self, keys: list[str]) -> list[str | None] | None:
        """Lê as chaves num único MGET. ``None`` indica Redis indisponível.

        O retorno distingue "chave ausente" (elemento ``None`` na lista) de "Redis
        indisponível" (retorno ``None``), que é o que permite responder 404 e 503
        conforme a causa real.
        """
        client = await self._ensure_client()
        if client is None:
            return None
        try:
            values = await client.mget(keys)
        except (RedisError, OSError):
            logger.exception("Erro ao ler %s no Redis", keys)
            # O cliente é preservado: o pool do redis-py reconecta sozinho na próxima
            # chamada. Anulá-lo era o que travava a API em 503 permanente.
            return None

        for key, value in zip(keys, values, strict=True):
            if value is not None:
                self.local_cache.set(key, value)
        return list(values)

    def _fallback(self, key: str) -> str:
        """Valor de cache local, ou exceção explicando por que não há resposta."""
        cached = self.local_cache.get_value(key)
        age = self.local_cache.get_age_seconds(key)
        if cached is None or age is None:
            raise RedisUnavailableError("Redis indisponível e nenhum valor em cache local", key=key)
        if age > self._settings.cache_ttl_seconds:
            raise RedisUnavailableError(
                f"Redis indisponível há mais de {self._settings.cache_ttl_seconds}s",
                key=key,
                cache_age=age,
            )
        logger.warning("Usando cache local para a chave '%s' (idade: %ds)", key, int(age))
        return cached

    async def get_values(self, keys: list[str]) -> list[str]:
        """Valores das chaves, com fallback para cache local.

        Levanta `KeyNotFoundError` se o Redis está no ar e a chave não existe, e
        `RedisUnavailableError` se o Redis está fora e o cache não serve.
        """
        values = await self._fetch(keys)
        if values is None:
            return [self._fallback(key) for key in keys]

        out: list[str] = []
        for key, value in zip(keys, values, strict=True):
            # `is not None`, e não truthiness: uma chave contendo string vazia é um
            # valor legítimo. Tratá-la como ausente fazia um Redis saudável virar 503.
            if value is None:
                raise KeyNotFoundError(key)
            out.append(value)
        return out

    async def get_value(self, key: str) -> str:
        return (await self.get_values([key]))[0]

    async def get_trading_hours(self) -> tuple[str, str]:
        """Horários de abertura e fechamento, lidos atomicamente num único MGET."""
        values = await self.get_values(
            [self._settings.redis_key_open, self._settings.redis_key_close]
        )
        return values[0], values[1]

    async def get_open_time(self) -> str:
        return await self.get_value(self._settings.redis_key_open)

    async def get_close_time(self) -> str:
        return await self.get_value(self._settings.redis_key_close)

    # --- diagnóstico -------------------------------------------------------

    async def is_connected(self) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            await client.ping()
        except (RedisError, OSError) as exc:
            # Logado: engolir silenciosamente tornava uma indisponibilidade
            # indepurável, já que /v1/health só dizia "disconnected".
            logger.warning("Ping ao Redis falhou: %s", exc)
            return False
        return True

    async def get_cache_status(self) -> dict[str, object]:
        ttl = self._settings.cache_ttl_seconds
        open_key = self._settings.redis_key_open
        close_key = self._settings.redis_key_close
        open_age = self.local_cache.get_age_seconds(open_key)
        close_age = self.local_cache.get_age_seconds(close_key)
        return {
            "redis_connected": await self.is_connected(),
            # `is not None`: idade 0.0 é um cache válido recém-escrito, não ausência.
            "open_cache_age_seconds": int(open_age) if open_age is not None else None,
            "close_cache_age_seconds": int(close_age) if close_age is not None else None,
            "open_cache_expired": self.local_cache.is_expired(open_key, ttl),
            "close_cache_expired": self.local_cache.is_expired(close_key, ttl),
            "cache_ttl_seconds": ttl,
        }

    @property
    def timezone(self) -> ZoneInfo:
        return self._settings.tz
