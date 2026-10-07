"""Configurações da aplicação B3 DateTime API.

A resolução de variáveis de ambiente é feita exclusivamente pelo pydantic-settings.
Não use ``os.getenv`` como default de campo: isso cria uma segunda fonte de ambiente,
avaliada no import, com nome diferente do que o pydantic-settings resolve.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# A seção de autenticação não está aqui: ela depende de API_KEY_REQUIRED e é anexada
# por create_app() (ver src/b3datetime/routers/openapi_examples.py::auth_description).
API_DESCRIPTION = """API para consultar horários de operação e dias de negociação da B3 (Bolsa de Valores de São Paulo).

## Características

* **Horários de Operação**: abertura e fechamento lidos do Redis, com cache local de 1 h
* **Dias de Negociação**: dias úteis na B3 segundo o calendário BVMF do `exchange_calendars`
* **Janela de dados**: o calendário cobre uma janela móvel; consulte `GET /v1/calendar-info`
  para os limites vigentes
* **Timezone**: todos os horários e datas usam America/Sao_Paulo

## Códigos de resposta

| Código | Quando |
|---|---|
| `200` | Sucesso |
| `400` | Período inválido em `/v1/trading-days`: ordem, span acima do máximo ou fora da janela |
| `404` | Redis disponível, mas a chave não existe |
| `422` | Data mal formada |
| `502` | Valor no Redis fora do formato `HH:MM` |
| `503` | Redis indisponível sem cache válido, ou calendário indisponível |

As URLs canônicas não têm barra final (`/docs/` responde 404). Código, guia de migração e
CHANGELOG: [github.com/rlquilez/b3datetime](https://github.com/rlquilez/b3datetime)."""


# Parâmetros de query que o redis-py aceita como credencial (``redis://h?password=x``
# vira o kwarg ``password``), mais os nomes usuais de segredo. Comparados sem caixa.
_QUERY_SENSIVEL = frozenset({"password", "pass", "pwd", "username", "user", "token", "secret"})
_REDIGIDO = "***"


def redact_url(url: str) -> str:
    """Remove as credenciais de uma URL, preservando todo o resto.

    Logar a URL do Redis crua escreve a senha em texto puro no stdout e em qualquer
    agregador de logs que colete o container. Garantias (``tests/property``):

    * **nunca levanta** — a URL é logada no lifespan; uma porta inválida (``:abc``)
      derrubava o arranque;
    * o userinfo vira ``***`` **com ou sem host** (``redis://:senha@/0`` e
      ``unix://:senha@/sock`` são válidas para o redis-py e vazavam inteiras);
    * credenciais na query (``?password=``) viram ``***``;
    * o resto fica intacto: host com a caixa e os colchetes do IPv6, porta (inclusive
      ``0`` e valores inválidos), path, demais parâmetros e fragmento.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<url inválida>"
    netloc = parts.netloc
    if "@" in netloc:
        # O host é o que vem depois do ÚLTIMO "@": uma senha não codificada pode conter "@".
        netloc = f"{_REDIGIDO}@{netloc.rsplit('@', 1)[1]}"
    query = parts.query
    if query:
        pares = parse_qsl(query, keep_blank_values=True)
        if any(chave.lower() in _QUERY_SENSIVEL for chave, _ in pares):
            redigidos = [(k, _REDIGIDO if k.lower() in _QUERY_SENSIVEL else v) for k, v in pares]
            # safe="*": "***" sai literal. Acrescentar caracteres seguros não muda nada.
            query = urlencode(redigidos, safe="*")  # pragma: no mutate
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


class Settings(BaseSettings):
    """Configurações da aplicação carregadas de variáveis de ambiente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # extra="ignore" é obrigatório: o default do pydantic-settings é "forbid", e o
        # DotEnvSettingsSource levanta erro para qualquer chave do .env que não seja
        # campo do modelo. Com "forbid", o `cp .env.example .env` documentado no README
        # impedia o import de b3datetime.config.
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
    api_version: str = "2.1.0"
    root_path: str = ""
    # Só afeta a documentação: com `true`, o OpenAPI declara o esquema `ApiKeyAuth` e
    # `GET /` informa que o header `apikey` é obrigatório. Quem valida a chave é o Kong;
    # a aplicação não tem — e não deve ganhar — código de autenticação.
    api_key_required: bool = False
    # Commit (SHA) do build em execução, gravado na imagem pelo CI (`ARG BUILD_SHA` →
    # `APP_BUILD`). É o que permite verificar, de fora, qual build a produção serve —
    # a versão só muda nas releases. Fora da imagem publicada, "local".
    app_build: str = "local"

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
    """Settings do processo, lidas do ambiente (e do ``.env``) na primeira chamada.

    Só o ``create_app()`` sem argumento as usa. Nada no pacote as instancia no import:
    um global de módulo lia o ``.env`` no ``import`` (e um ``TIMEZONE`` inválido
    derrubava o import), e os routers liam essas settings globais em vez das da app.
    """
    return Settings()


def get_current_datetime(tz: ZoneInfo) -> datetime:
    """Data e hora atual no timezone dado — o das settings da app, sempre explícito."""
    return datetime.now(tz)
