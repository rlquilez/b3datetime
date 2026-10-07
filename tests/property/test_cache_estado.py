"""O cache local como máquina de estados, em qualquer fuso horário.

Sequências arbitrárias de "grava", "o tempo passa" e "consulta", com o relógio da
aplicação num fuso sorteado entre todos os do tzdata — inclusive os que têm horário de
verão. Invariantes:

* a idade de uma entrada é o tempo **real** decorrido desde a gravação (era relógio de
  parede: na volta do horário de verão, 2 h reais viravam 1 h e um cache vencido seguia
  sendo servido);
* ``0.0`` é idade legítima, nunca "ausente";
* expirado ⇔ idade > TTL (estrito), e chave ausente conta como expirada.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from b3datetime.services.redis_service import RedisCache

CHAVES = st.sampled_from(["b3:open", "b3:close"])
TTL = 3600
ORIGEM = datetime(2000, 1, 1, tzinfo=UTC)

# Fusos com horário de verão (ou que já tiveram: São Paulo até 2019). Sortear um fuso e um
# instante ao acaso quase nunca atravessa uma virada — a sabotagem "relógio de parede"
# passava despercebida. Por isso as sequências começam, na maior parte das vezes, até 6 h
# antes de uma virada REAL, calculada do tzdata.
FUSOS_COM_HORARIO_DE_VERAO = (
    "America/New_York",
    "America/Sao_Paulo",
    "Europe/London",
    "Europe/Lisbon",
    "Australia/Sydney",
    "America/Santiago",
)


def _viradas(nome: str, anos: range) -> list[datetime]:
    """Instantes (UTC) em que o deslocamento do fuso muda, varrendo de hora em hora."""
    fuso = ZoneInfo(nome)
    viradas: list[datetime] = []
    instante = datetime(anos.start, 1, 1, tzinfo=UTC)
    fim = datetime(anos.stop, 1, 1, tzinfo=UTC)
    anterior = instante.astimezone(fuso).utcoffset()
    while instante < fim:
        instante += timedelta(hours=1)
        atual = instante.astimezone(fuso).utcoffset()
        if atual != anterior:
            viradas.append(instante)
            anterior = atual
    return viradas


VIRADAS = [
    (ZoneInfo(nome), virada)
    for nome in FUSOS_COM_HORARIO_DE_VERAO
    for virada in _viradas(nome, range(2010, 2021))
]

PERTO_DE_UMA_VIRADA = st.tuples(
    st.sampled_from(VIRADAS), st.integers(min_value=0, max_value=6 * 3600)
).map(lambda par: (par[0][0], par[0][1] - timedelta(seconds=par[1])))
QUALQUER_INSTANTE = st.tuples(
    st.timezones(), st.integers(min_value=0, max_value=36 * 365 * 86400)
).map(lambda par: (par[0], ORIGEM + timedelta(seconds=par[1])))


class CacheEmQualquerFuso(RuleBasedStateMachine):
    @initialize(partida=st.one_of(PERTO_DE_UMA_VIRADA, PERTO_DE_UMA_VIRADA, QUALQUER_INSTANTE))
    def iniciar(self, partida: tuple[ZoneInfo, datetime]) -> None:
        self.fuso, self.instante = partida  # o instante é o tempo real, em UTC
        self.gravado_em: dict[str, datetime] = {}
        self.cache = RedisCache(now_fn=lambda: self.instante.astimezone(self.fuso))

    @rule(chave=CHAVES, valor=st.text(max_size=5))
    def gravar(self, chave: str, valor: str) -> None:
        self.cache.set(chave, valor)
        self.gravado_em[chave] = self.instante

    @rule(segundos=st.integers(min_value=0, max_value=4 * 3600))
    def passar_o_tempo(self, segundos: int) -> None:
        self.instante += timedelta(seconds=segundos)

    @rule(chave=CHAVES)
    def consultar(self, chave: str) -> None:
        idade = self.cache.get_age_seconds(chave)
        if chave not in self.gravado_em:
            assert idade is None
            assert self.cache.is_expired(chave, TTL)
            return
        real = (self.instante - self.gravado_em[chave]).total_seconds()
        assert idade == real
        assert idade is not None  # 0.0 é idade, não ausência
        assert self.cache.is_expired(chave, TTL) == (real > TTL)

    @invariant()
    def chaves_gravadas_estao_no_cache(self) -> None:
        for chave in self.gravado_em:
            assert self.cache.get_value(chave) is not None


TestCacheEmQualquerFuso = CacheEmQualquerFuso.TestCase
