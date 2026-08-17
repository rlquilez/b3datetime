"""Configurações da aplicação B3 DateTime API.

A resolução de variáveis de ambiente é feita exclusivamente pelo pydantic-settings.
Não use ``os.getenv`` como default de campo: isso cria uma segunda fonte de ambiente,
avaliada no import, com nome diferente do que o pydantic-settings resolve.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DESCRIPTION = """
API para consultar horários de operação e dias de negociação da B3 (Bolsa de Valores de São Paulo).

## Autenticação

Todas as requisições devem incluir o header `apikey` com uma chave válida gerenciada pelo Kong Gateway.

## Características

* **Horários de Operação**: Consulte horários de abertura e fechamento via Redis (cache local de 1h)
* **Dias de Negociação**: Valide se um dia é útil na B3 usando exchange_calendars
* **Janela de dados**: O calendário cobre uma janela móvel; consulte `GET /v1/calendar-info`
  para os limites vigentes
* **Timezone**: Todos os horários e datas utilizam timezone America/Sao_Paulo
"""


def redact_url(url: str) -> str:
    """Remove usuário e senha de uma URL, preservando esquema, host, porta e path.

    Logar a URL do Redis crua escreve a senha em texto puro no stdout e em qualquer
    agregador de logs que colete o container.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<url inválida>"
    if not parts.hostname:
        return url
    netloc = parts.hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    if parts.username or parts.password:
        netloc = f"***@{netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class Settings(BaseSettings):
    """Configurações da aplicação carregadas de variáveis de ambiente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # extra="ignore" é obrigatório: o default do pydantic-settings é "forbid", e o
        # DotEnvSettingsSource levanta erro para qualquer chave do .env que não seja
        # campo do modelo. Com "forbid", o `cp .env.example .env` documentado no README
        # impedia o import de src.config.
        extra="ignore",
    )

    # --- Redis ---
    # REDIS_URL_ENV é o nome documentado e tem precedência; REDIS_URL é aceito porque é
    # o nome que Heroku, Railway, Render, Fly.io e templates de docker-compose injetam
    # automaticamente. A precedência aqui é explícita, e não um acidente de ordem de
    # avaliação como era com os defaults via os.getenv.
    redis_url: str = Field(
        default="redis://localhost:6379",
        validation_alias=AliasChoices("REDIS_URL_ENV", "REDIS_URL"),
    )
    redis_key_open: str = "b3:trading:hours:open"
    redis_key_close: str = "b3:trading:hours:close"

    # Intervalo mínimo entre tentativas de reconexão ao Redis, em segundos.
    redis_reconnect_interval_seconds: float = 30.0
    redis_socket_timeout_seconds: float = 5.0

    # --- Cache local ---
    cache_ttl_seconds: int = 3600

    # --- Timezone ---
    timezone: str = "America/Sao_Paulo"

    # --- Calendário ---
    exchange_name: str = "BVMF"
    # Quantos anos para trás o calendário é construído a partir de hoje. A janela é
    # móvel; os limites reais são sempre lidos do calendário construído, nunca daqui.
    calendar_start_offset_years: int = 10
    # Span máximo aceito em /v1/trading-days. Sem esse limite, um único request pode
    # alocar centenas de MB e monopolizar o event loop por mais de um minuto.
    max_range_days: int = 3660

    # --- API ---
    api_title: str = "B3 DateTime API"
    api_description: str = API_DESCRIPTION
    api_version: str = "2.0.0"
    root_path: str = ""

    @property
    def tz(self) -> ZoneInfo:
        """Timezone configurado."""
        return ZoneInfo(self.timezone)

    @property
    def redis_url_safe(self) -> str:
        """URL do Redis com as credenciais removidas, para uso em logs."""
        return redact_url(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    """Instância de configurações, memoizada por processo."""
    return Settings()


# Instância de conveniência para os metadados estáticos consumidos por `create_app()`.
# Em código novo prefira `get_settings()` ou a dependência `SettingsDep`.
settings = get_settings()

TZ = settings.tz


def get_current_datetime(tz: ZoneInfo | None = None) -> datetime:
    """Data e hora atual no timezone configurado."""
    return datetime.now(tz or TZ)
