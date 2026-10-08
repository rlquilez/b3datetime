"""O design system dos diagramas, como dados: a paleta por papel e o ``config`` canônico.

Fonte única para os testes estáticos (``test_estilo.py``) e espelho exato do que a skill
``.claude/skills/mermaid-design/SKILL.md`` ensina — mudar uma cor é mudar aqui e lá, e o
render no Chromium (:mod:`tests.docs.renderizador`) confere de novo o contraste.

A paleta é a "Soft Minimal" com o mínimo de ajuste para contraste: texto ≥ 4,5:1 sobre a
superfície que o próprio diagrama pinta e linhas ≥ 3:1 nos dois fundos do GitHub
(``#ffffff`` e ``#0d1117``). O único ajuste foi o das conexões: ``#94A3B8`` → ``#8895A9``
(2,56:1 → 3,07:1 no fundo claro; 7,0:1 no escuro).
"""

from __future__ import annotations

from typing import Any

FONTE = (
    "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans, Helvetica, Arial, sans-serif"
)
LINHA = "#8895A9"

# Papéis de nó (``classDef <papel> ...``): fundo, borda, espessura e texto.
CLASSES = {
    "entrada": "fill:#FFFFFF,stroke:#DCE4EC,stroke-width:1.5px,color:#334155",
    "gateway": "fill:#F8FAFD,stroke:#B9CBDF,stroke-width:1.5px,color:#344C68",
    "principal": "fill:#E8F7F2,stroke:#0F9F87,stroke-width:2.5px,color:#075E50",
    "servico": "fill:#FFFFFF,stroke:#B9DCD1,stroke-width:1.5px,color:#356C60",
    "dados": "fill:#FFFAF4,stroke:#E6CEB1,stroke-width:1.5px,color:#8B623C",
    "externo": "fill:#FFFFFF,stroke:#DCE4EC,stroke-width:1.5px,color:#64748B",
    "gate": "fill:#FFFFFF,stroke:#334155,stroke-width:2px,color:#334155",
    "falha": "fill:#FDF3F4,stroke:#EBC4CB,stroke-width:1.5px,color:#9B3B4D",
    # Estados do stateDiagram (saudável, degradado, não saudável).
    "saudavel": "fill:#E8F7F2,stroke:#0F9F87,stroke-width:2px,color:#075E50",
    "degradado": "fill:#FFFAF4,stroke:#E6CEB1,stroke-width:1.5px,color:#8B623C",
}

# Papéis de subgrafo (``style <id> ...``).
GRUPOS = {
    "container": "fill:#F8FCFA,stroke:#C8E5DA,stroke-width:1.5px,color:#257361",
    "estatica": "fill:#F8FAFD,stroke:#B9CBDF,stroke-width:1.5px,color:#344C68",
    "consolidacao": "fill:#FFFAF4,stroke:#E6CEB1,stroke-width:1.5px,color:#8B623C",
}

# O painel claro que envolve as mensagens de uma sequência: sem ele, o texto das
# mensagens fica direto sobre o #0d1117 do modo escuro.
PAINEL = "rect rgb(248, 250, 252)"

_BASE = {
    "fontFamily": FONTE,
    "fontSize": "15px",
    "primaryColor": "#FFFFFF",
    "primaryTextColor": "#334155",
    "primaryBorderColor": "#DCE4EC",
    "nodeBorder": "#DCE4EC",
    "lineColor": LINHA,
    "textColor": "#475569",
    "edgeLabelBackground": "#FFFFFF",
}

# Ajustes de layout que cada diagrama pode escolher, com a faixa aceita.
AJUSTES = {
    ("layout",): ("dagre", "elk"),
    ("flowchart", "nodeSpacing"): range(10, 91),
    ("flowchart", "rankSpacing"): range(10, 91),
    ("flowchart", "wrappingWidth"): range(200, 801),
    ("sequence", "actorMargin"): range(30, 91),
}


def config_fluxo() -> dict[str, Any]:
    """``config`` de um flowchart, com os valores padrão dos ajustes."""
    return {
        "theme": "base",
        "look": "neo",
        "layout": "dagre",
        "fontFamily": FONTE,
        "htmlLabels": False,
        "themeCSS": (
            ".edgeLabel rect { opacity: 1 !important; } "
            ".edge-thickness-normal { stroke-width: 1.5px !important; }"
        ),
        "themeVariables": {
            **_BASE,
            "clusterBkg": "#F8FCFA",
            "clusterBorder": "#C8E5DA",
            "titleColor": "#257361",
        },
        "flowchart": {
            "curve": "basis",
            "nodeSpacing": 60,
            "rankSpacing": 70,
            "padding": 18,
            "wrappingWidth": 400,
            "diagramPadding": 24,
        },
    }


def config_estado() -> dict[str, Any]:
    """``config`` de um stateDiagram-v2 (rótulos HTML: com ``htmlLabels: false`` o nome
    do estado sai alinhado à esquerda)."""
    return {
        "theme": "base",
        "look": "neo",
        "layout": "dagre",
        "fontFamily": FONTE,
        "htmlLabels": True,
        "themeCSS": (
            ".edgeLabel rect { opacity: 1 !important; } "
            ".labelBkg, .edgeLabel p { background-color: #FFFFFF !important; }"
        ),
        "themeVariables": {
            **_BASE,
            "transitionColor": LINHA,
            "transitionLabelColor": "#475569",
            "noteBkgColor": "#F8FAFD",
            "noteBorderColor": "#B9CBDF",
            "noteTextColor": "#344C68",
        },
        "state": {"nodeSpacing": 60, "rankSpacing": 70},
    }


def config_sequencia() -> dict[str, Any]:
    """``config`` de um sequenceDiagram (o halo do ``themeCSS`` apaga as linhas de vida
    que passariam por baixo do texto das mensagens)."""
    return {
        "theme": "base",
        "look": "neo",
        "fontFamily": FONTE,
        "themeCSS": (
            ".messageText, .loopText, .loopText tspan, .sectionTitle, .sectionTitle tspan "
            "{ paint-order: stroke; stroke: #F8FAFC; stroke-width: 12px; "
            "stroke-linejoin: round; }"
        ),
        "themeVariables": {
            "fontFamily": FONTE,
            "fontSize": "15px",
            "actorBkg": "#FFFFFF",
            "actorBorder": "#B9CBDF",
            "actorTextColor": "#334155",
            "actorLineColor": LINHA,
            "signalColor": LINHA,
            "signalTextColor": "#334155",
            "labelBoxBkgColor": "#F8FAFD",
            "labelBoxBorderColor": "#B9CBDF",
            "labelTextColor": "#344C68",
            "loopTextColor": "#344C68",
            "noteBkgColor": "#FFFAF4",
            "noteBorderColor": "#E6CEB1",
            "noteTextColor": "#8B623C",
            "activationBkgColor": "#E8F7F2",
            "activationBorderColor": "#0F9F87",
        },
        "sequence": {
            "mirrorActors": False,
            "width": 90,
            "actorMargin": 30,
            "boxMargin": 12,
            "messageMargin": 42,
            "noteMargin": 12,
            "diagramMarginX": 24,
        },
    }


CONFIGS = {
    "flowchart": config_fluxo,
    "stateDiagram-v2": config_estado,
    "sequenceDiagram": config_sequencia,
}


def _cores(valor: object) -> set[str]:
    if isinstance(valor, dict):
        return set().union(*(_cores(v) for v in valor.values()))
    texto = str(valor)
    return {texto[i : i + 7].upper() for i in range(len(texto)) if texto.startswith("#", i)}


# Toda cor que um diagrama pode conter: as dos papéis e as do config canônico.
CORES = (
    _cores(CLASSES)
    | _cores(GRUPOS)
    | _cores(config_fluxo())
    | _cores(config_estado())
    | _cores(config_sequencia())
)
