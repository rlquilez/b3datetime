"""O design system, verificado no código-fonte de cada diagrama — sem navegador nem Node.

Cada regra aqui existe por um defeito visto no GitHub ou numa revisão das capturas: a
lista e o porquê de cada uma estão na skill ``.claude/skills/mermaid-design/SKILL.md``.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from tests.docs.agentic import LIMITE_DE_ROTULO, para_agentic
from tests.docs.design import AJUSTES, CLASSES, CONFIGS, CORES, GRUPOS, PAINEL
from tests.docs.diagramas import FRONTMATTER, Diagrama, diagramas, extrair

TODOS = diagramas()
IDS = [d.id for d in TODOS]
LIMITE_DE_TRANSICAO = 28

MARKDOWN = re.compile(r'"`(.*?)`"', re.DOTALL)
ASPAS = re.compile(r'"([^"`]*)"')
MENSAGEM = re.compile(
    r"^\s*(?:\S+\s*(?:-->>|->>|-->|->|--x|-x)\s*\S+|Note .+?|[^:]*-->[^:]*):\s*(.+)$"
)
BLOCO_SEQUENCIA = re.compile(r"^\s*(?:alt|else|loop|opt|par|critical)\s+(.+)$")
TAG = re.compile(r"<(/?[A-Za-z][^>]*)>")
EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿️]")
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
CLASSDEF = re.compile(r"^\s*classDef (\S+) (\S+)\s*$", re.MULTILINE)
STYLE = re.compile(r"^\s*style (\S+) (\S+)\s*$", re.MULTILINE)


def configuracao(diagrama: Diagrama) -> dict[str, Any]:
    """O ``config`` do frontmatter YAML do diagrama."""
    achado = FRONTMATTER.match(diagrama.fonte)
    assert achado, f"{diagrama.arquivo}#{diagrama.indice}: sem frontmatter `---\\nconfig: …`"
    documento = yaml.safe_load(achado.group(1))
    assert isinstance(documento, dict)
    config = documento.get("config")
    assert isinstance(config, dict), "o frontmatter precisa de uma chave `config`"
    return config


def rotulos(diagrama: Diagrama) -> list[str]:
    """Cada linha de texto que o leitor vê: rótulos de nó, aresta, subgrafo e mensagem."""
    corpo = diagrama.corpo
    linhas: list[str] = []
    for bloco in MARKDOWN.findall(corpo):
        linhas += [linha.strip().replace("**", "") for linha in bloco.split("\n")]
    sem_markdown = MARKDOWN.sub("", corpo)
    for texto in ASPAS.findall(sem_markdown):
        linhas += re.split(r"<br\s*/?>", texto)
    for linha in sem_markdown.splitlines():
        achado = MENSAGEM.match(linha) or BLOCO_SEQUENCIA.match(linha)
        if achado and '"' not in linha:
            linhas += re.split(r"<br\s*/?>", achado.group(1))
    return [linha.strip() for linha in linhas if linha.strip()]


def test_encontra_os_diagramas_das_duas_paginas_e_os_modelos() -> None:
    arquivos = {d.arquivo for d in TODOS}
    assert {"README.md", "tests/README.md"} <= arquivos
    assert any(a.endswith(".mmd") for a in arquivos), "os modelos da skill sumiram"


def test_extrai_blocos_na_ordem_com_a_linha() -> None:
    texto = "# T\n\n```mermaid\nflowchart TB\n  a --> b\n```\n\ntexto\n\n```mermaid \nsequenceDiagram\n```\n"
    achados = extrair("x.md", texto)
    assert [(d.indice, d.linha, d.tipo) for d in achados] == [
        (0, 3, "flowchart"),
        (1, 10, "sequenceDiagram"),
    ]
    assert achados[0].id == "x-0"


@pytest.mark.parametrize("diagrama", TODOS, ids=IDS)
def test_frontmatter_canonico(diagrama: Diagrama) -> None:
    """O ``config`` é exatamente o da família, salvo os ajustes de layout permitidos."""
    assert diagrama.tipo in CONFIGS, f"tipo fora do design system: {diagrama.tipo}"
    config = configuracao(diagrama)
    canonico = CONFIGS[diagrama.tipo]()
    for caminho, aceitos in AJUSTES.items():
        origem: Any = config
        destino: Any = canonico
        for chave in caminho[:-1]:
            origem, destino = origem.get(chave, {}), destino.get(chave, {})
        if caminho[-1] in origem and caminho[-1] in destino:
            assert origem[caminho[-1]] in aceitos, f"{'.'.join(caminho)} fora de {aceitos}"
            destino[caminho[-1]] = origem[caminho[-1]]
    assert config == canonico


@pytest.mark.parametrize("diagrama", TODOS, ids=IDS)
def test_cores_so_da_paleta(diagrama: Diagrama) -> None:
    for papel, estilo in CLASSDEF.findall(diagrama.corpo):
        assert CLASSES.get(papel) == estilo, f"classDef {papel} fora da paleta: {estilo}"
    for grupo, estilo in STYLE.findall(diagrama.corpo):
        assert estilo in GRUPOS.values(), f"style {grupo} fora da paleta: {estilo}"
    fora = {cor.upper() for cor in HEX.findall(diagrama.fonte)} - CORES
    assert not fora, f"cores fora da paleta: {sorted(fora)}"
    sem_painel = diagrama.corpo.replace(PAINEL, "")
    assert not re.search(r"\b(?:rgba?|hsla?)\(", sem_painel), "cor fora do formato #RRGGBB"
    assert "linkStyle" not in diagrama.corpo, (
        "linkStyle: a espessura das arestas vem do themeCSS, e `linkStyle default` torna "
        "visíveis os elos invisíveis (~~~)"
    )


@pytest.mark.parametrize("diagrama", TODOS, ids=IDS)
def test_sem_diretiva_init(diagrama: Diagrama) -> None:
    assert "%%{" not in diagrama.fonte, "configuração vai no frontmatter, não em %%{init}%%"


@pytest.mark.parametrize("diagrama", TODOS, ids=IDS)
def test_sem_tag_html_alem_de_br(diagrama: Diagrama) -> None:
    tags = {tag for tag in TAG.findall(diagrama.corpo) if tag.rstrip("/ ").lower() != "br"}
    assert not tags, f"tags HTML aparecem literais no GitHub: {sorted(tags)}"


@pytest.mark.parametrize("diagrama", TODOS, ids=IDS)
def test_sem_emoji(diagrama: Diagrama) -> None:
    assert not EMOJI.findall(diagrama.fonte)


@pytest.mark.parametrize("diagrama", TODOS, ids=IDS)
def test_rotulos_curtos(diagrama: Diagrama) -> None:
    longos = [r for r in rotulos(diagrama) if len(r) > LIMITE_DE_ROTULO]
    assert not longos, f"linhas com mais de {LIMITE_DE_ROTULO} caracteres: {longos}"


@pytest.mark.parametrize(
    "diagrama", [d for d in TODOS if d.tipo == "stateDiagram-v2"], ids=lambda d: d.id
)
def test_transicao_de_estado_numa_linha(diagrama: Diagrama) -> None:
    """O rótulo de transição (HTML) quebra em ~200 px: acima disso, vira duas linhas."""
    transicoes = re.findall(r"-->\s*\S+\s*:\s*(.+)$", diagrama.corpo, re.MULTILINE)
    assert transicoes
    longas = [t for t in transicoes if len(t.strip()) > LIMITE_DE_TRANSICAO]
    assert not longas, f"transições com mais de {LIMITE_DE_TRANSICAO} caracteres: {longas}"


@pytest.mark.parametrize("diagrama", TODOS, ids=IDS)
def test_sem_dunder_em_markdown_string(diagrama: Diagrama) -> None:
    """Numa markdown string, ``__main__`` vira "main" em negrito — e não há escape que o
    GitHub respeite (``\\_`` e ``&#95;`` também falham)."""
    assert not [b for b in MARKDOWN.findall(diagrama.corpo) if "__" in b]


@pytest.mark.parametrize(
    "diagrama", [d for d in TODOS if d.tipo == "sequenceDiagram"], ids=lambda d: d.id
)
def test_sequencia_com_painel_e_sem_numeracao(diagrama: Diagrama) -> None:
    linhas = [linha.strip() for linha in diagrama.corpo.strip().splitlines()]
    assert PAINEL in linhas, f"falta o painel `{PAINEL}` em volta das mensagens"
    assert linhas[-1] == "end", "o painel fecha no último `end`"
    assert "autonumber" not in linhas, "o círculo do autonumber não atinge 4,5:1"


def test_conversao_para_o_agentic_mermaid() -> None:
    fonte = (
        '---\nconfig:\n  theme: base\n  themeCSS: ".x { y: 1; }"\n---\n'
        "sequenceDiagram\n    participant A\n    rect rgb(248, 250, 252)\n"
        '    A->>A: oi\n    end\nflowchart TB\n    a("`**Título**\n    sub`")\n'
    )
    convertido = para_agentic(fonte)
    assert "themeCSS" not in convertido
    assert "rect rgb" not in convertido
    assert not convertido.rstrip().endswith("end")
    assert 'a("Título<br>sub")' in convertido
