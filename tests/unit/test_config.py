"""Configurações e resolução de variáveis de ambiente."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from src.config import Settings, get_settings, redact_url

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_versao_sincronizada_com_pyproject() -> None:
    """release.yml confere config.py, README e CHANGELOG, mas não o pyproject.toml —
    este teste é a única guarda da quarta cópia da versão."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == Settings(_env_file=None).api_version


def test_versao_sincronizada_com_readme_e_changelog() -> None:
    """Mesma verificação que o job `verify` do release.yml faz na tag, antecipada."""
    version = Settings(_env_file=None).api_version
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"Versão atual: {version}" in readme
    secao = rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$"
    assert re.search(secao, changelog, re.MULTILINE), f"CHANGELOG sem a seção [{version}]"


def test_defaults_sem_ambiente() -> None:
    s = Settings(_env_file=None)
    assert s.redis_url == "redis://localhost:6379"
    assert s.redis_key_open == "b3:trading:hours:open"
    assert s.redis_key_close == "b3:trading:hours:close"
    assert s.cache_ttl_seconds == 3600
    assert s.timezone == "America/Sao_Paulo"
    assert s.exchange_name == "BVMF"


def test_redis_url_env_honrado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL_ENV", "redis://documentado:6379")
    assert Settings(_env_file=None).redis_url == "redis://documentado:6379"


def test_redis_url_honrado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL_ENV", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://plataforma:6379")
    assert Settings(_env_file=None).redis_url == "redis://plataforma:6379"


def test_redis_url_env_tem_precedencia_sobre_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressão: REDIS_URL vencia silenciosamente o nome documentado.

    REDIS_URL é injetado automaticamente por Heroku, Railway, Render, Fly.io e
    templates de docker-compose. Quando vencia, um deploy com REDIS_URL_ENV correto
    conectava no Redis errado sem nenhum aviso.
    """
    monkeypatch.setenv("REDIS_URL_ENV", "redis://producao:6379")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    assert Settings(_env_file=None).redis_url == "redis://producao:6379"


def test_env_example_do_repositorio_nao_impede_o_boot(tmp_path: Path) -> None:
    """Regressão end-to-end: `cp .env.example .env` fazia `Settings()` levantar
    no import, quebrando exatamente o caminho de setup documentado no README.

    Este teste cobre a *combinação* que consertou o boot — o alias
    `REDIS_URL_ENV` mais `extra="ignore"` — e falha somente no estado original,
    com as duas coisas ausentes. Cada peça tem, além deste, o seu próprio teste:
    `test_redis_url_env_tem_precedencia_sobre_redis_url` para o alias e
    `test_chave_desconhecida_no_env_nao_impede_o_boot` para o `extra`.

    O arquivo real do repositório é lido de propósito, para que `.env.example` e o
    modelo nunca voltem a divergir sem que um teste perceba.
    """
    example = REPO_ROOT / ".env.example"
    assert example.exists(), "o .env.example do repositório sumiu"

    env_file = tmp_path / ".env"
    env_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    s = Settings(_env_file=str(env_file))
    assert s.redis_url.startswith("redis://")


def test_chave_desconhecida_no_env_nao_impede_o_boot(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CHAVE_QUE_NAO_EXISTE=1\nREDIS_URL_ENV=redis://x:6379\n", encoding="utf-8")
    assert Settings(_env_file=str(env_file)).redis_url == "redis://x:6379"


def test_get_current_datetime_tem_fuso() -> None:
    from src.config import get_current_datetime

    now = get_current_datetime()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None


def test_get_settings_e_memoizado() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        ("redis://localhost:6379", "redis://localhost:6379"),
        ("redis://user:secret@host:6379", "redis://***@host:6379"),
        ("redis://user:secret@host:6379/0", "redis://***@host:6379/0"),
        ("rediss://:senha@prod.example.com:6380", "rediss://***@prod.example.com:6380"),
    ],
)
def test_redact_url_remove_credenciais(url: str, esperado: str) -> None:
    """Regressão: a URL do Redis era logada crua, com a senha em texto puro."""
    redigida = redact_url(url)
    assert redigida == esperado
    assert "secret" not in redigida
    assert "senha" not in redigida


def test_redis_url_safe_nao_vaza_senha() -> None:
    s = Settings(_env_file=None, REDIS_URL_ENV="redis://admin:hunter2@redis-prod:6379")
    assert "hunter2" not in s.redis_url_safe
    assert "redis-prod:6379" in s.redis_url_safe


def test_tz_property() -> None:
    assert str(Settings(_env_file=None).tz) == "America/Sao_Paulo"


def test_api_key_required_desligado_por_padrao() -> None:
    """Não há autenticação no momento; a documentação não pode prometer um header."""
    assert Settings(_env_file=None).api_key_required is False


def test_api_key_required_lido_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY_REQUIRED", "true")
    assert Settings(_env_file=None).api_key_required is True


def test_redact_url_com_entrada_sem_host() -> None:
    """Uma string que não é URL não deve estourar nem ser propagada inteira."""
    assert redact_url("nao-e-uma-url") == "nao-e-uma-url"


def test_redact_url_com_entrada_invalida() -> None:
    # IPv6 malformado faz urlsplit levantar ValueError.
    assert redact_url("redis://[::1") == "<url inválida>"


def test_configure_logging_e_idempotente() -> None:
    from src.main import configure_logging

    configure_logging()
    configure_logging()
