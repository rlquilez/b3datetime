"""``redact_url``: a URL do Redis vai para o log, então a redação nunca pode falhar.

Propriedades, sobre URLs geradas — não sobre meia dúzia de exemplos escolhidos:

* **nunca levanta**, para qualquer texto: a URL é logada no lifespan, e uma exceção ali
  derrubava o arranque por causa de uma porta digitada errado;
* **nunca vaza credencial**: nem no userinfo (com ou sem host — ``redis://:senha@/0`` e
  ``unix://:senha@/run/redis.sock`` são URLs válidas para o redis-py), nem em parâmetros de query
  que o redis-py aceita como credencial (``?password=``);
* **preserva o resto**: host com a caixa e os colchetes do IPv6, porta (inclusive ``0``),
  path e os demais parâmetros;
* **é idempotente**: redigir de novo não muda nada.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, quote, urlsplit

from hypothesis import example, given
from hypothesis import strategies as st

from b3datetime.config import redact_url

ESQUEMAS = st.sampled_from(["redis", "rediss", "unix"])
# Credenciais "marcadas": longas o bastante para não aparecerem por acaso no resto da URL.
SEGREDOS = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S"), exclude_characters="\x00"),
    min_size=1,
    max_size=24,
).map(lambda s: f"S3GR3D0-{s}")
HOSTS = st.one_of(
    st.from_regex(r"[A-Za-z][A-Za-z0-9-]{0,20}(\.[A-Za-z0-9-]{1,10}){0,2}", fullmatch=True),
    st.ip_addresses(v=4).map(str),
    st.ip_addresses(v=6).map(lambda ip: f"[{ip}]"),
    st.just(""),  # sem host: redis://:senha@/0 e unix://:senha@/tmp/r.sock
)
PORTAS = st.one_of(st.none(), st.integers(0, 65535).map(str), st.just("abc"), st.just("99999"))
PATHS = st.sampled_from(["", "/0", "/15", "/run/redis/redis.sock"])
CHAVES_SENSIVEIS = st.sampled_from(["password", "PASSWORD", "username", "user", "token"])


def _netloc(usuario: str | None, senha: str | None, host: str, porta: str | None) -> str:
    userinfo = ""
    if usuario is not None or senha is not None:
        userinfo = quote(usuario or "", safe="") + (
            ":" + quote(senha, safe="") if senha is not None else ""
        )
        userinfo += "@"
    return f"{userinfo}{host}{':' + porta if porta is not None else ''}"


@given(st.text())
@example("redis://u:p@h:abc")
@example("redis://u:p@h:99999")
@example("redis://[::1")
def test_nunca_levanta(qualquer: str) -> None:
    assert isinstance(redact_url(qualquer), str)


@given(
    esquema=ESQUEMAS,
    usuario=st.one_of(st.none(), SEGREDOS),
    senha=st.one_of(st.none(), SEGREDOS),
    host=HOSTS,
    porta=PORTAS,
    path=PATHS,
)
@example(esquema="redis", usuario=None, senha="S3GR3D0-x", host="", porta=None, path="/0")
@example(
    esquema="unix", usuario=None, senha="S3GR3D0-x", host="", porta=None, path="/run/redis.sock"
)
def test_userinfo_nunca_vaza(
    esquema: str, usuario: str | None, senha: str | None, host: str, porta: str | None, path: str
) -> None:
    url = f"{esquema}://{_netloc(usuario, senha, host, porta)}{path}"
    redigida = redact_url(url)
    for segredo in (usuario, senha):
        if segredo:
            assert segredo not in redigida
            assert quote(segredo, safe="") not in redigida


@given(chave=CHAVES_SENSIVEIS, segredo=SEGREDOS, outro=st.sampled_from(["db=2", "ssl=true"]))
def test_credencial_na_query_nunca_vaza(chave: str, segredo: str, outro: str) -> None:
    url = f"redis://host:6379/0?{outro}&{chave}={quote(segredo, safe='')}"
    redigida = redact_url(url)
    assert segredo not in redigida
    assert quote(segredo, safe="") not in redigida
    consulta = dict(parse_qsl(urlsplit(redigida).query, keep_blank_values=True))
    assert consulta[chave] == "***"
    chave_outro, valor_outro = outro.split("=")
    assert consulta[chave_outro] == valor_outro  # o resto da query é preservado


@given(host=HOSTS.filter(bool), porta=PORTAS, path=PATHS, senha=SEGREDOS)
def test_preserva_host_porta_e_path(host: str, porta: str | None, path: str, senha: str) -> None:
    sem_credencial = f"redis://{_netloc(None, None, host, porta)}{path}"
    com_credencial = f"redis://{_netloc('u', senha, host, porta)}{path}"
    assert redact_url(sem_credencial) == sem_credencial
    assert redact_url(com_credencial) == f"redis://***@{_netloc(None, None, host, porta)}{path}"


@given(st.text())
def test_idempotente(qualquer: str) -> None:
    uma_vez = redact_url(qualquer)
    assert redact_url(uma_vez) == uma_vez
