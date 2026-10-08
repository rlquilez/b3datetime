"""Render fiel ao GitHub: o mermaid.js da versão que o GitHub usa, com o ``initialize`` dele,
no Chromium, sobre os dois fundos do iframe — e a medição do que o leitor de fato vê.

Por que existe: os diagramas já foram "validados" com o mermaid 11.4 + dagre enquanto o
GitHub desenhava com o 12.1 + ELK; e um rótulo cortado só aparecia no navegador. Aqui:

* **versão**: ``node_modules/mermaid`` fixado em ``tests/docs/package.json`` na versão do
  GitHub (como reverificar: ``.claude/skills/mermaid-design/SKILL.md``);
* **configuração**: :data:`INICIALIZAR` reproduz o ``mermaid.initialize`` do bundle do
  GitHub (``securityLevel: "antiscript"``, ``theme`` pelo modo de cor, paddings);
* **fundo**: ``#ffffff`` no modo claro e ``#0d1117`` no escuro (``--bgColor-default``).

O que se mede, por diagrama e modo: erro de render; rótulo cortado ou que transborda a
forma; tag HTML visível; nós sobrepostos; contraste de **cada texto contra a superfície
realmente pintada abaixo dele** (``elementsFromPoint``, com transparências compostas) e
de cada linha contra o fundo. Uso direto: ``python -m tests.docs.renderizador --saida DIR``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.docs.diagramas import Diagrama, diagramas

if TYPE_CHECKING:
    from playwright.sync_api import Page

PASTA = Path(__file__).resolve().parent
MERMAID_JS = PASTA / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"
FUNDOS = {"claro": "#ffffff", "escuro": "#0d1117"}
# Largura do iframe do diagrama no github.com (medida com Playwright em 2026-10-07): 1012 px
# na visualização de um arquivo .md, mas só 838 px no README da página inicial do
# repositório — a que mais gente vê. Os modelos da skill usam a mais estreita.
COLUNA = 1012
COLUNA_DA_PAGINA_INICIAL = 838


def coluna(diagrama: Diagrama) -> int:
    """A largura em que o GitHub desenha este diagrama."""
    estreita = diagrama.arquivo == "README.md" or diagrama.arquivo.endswith(".mmd")
    return COLUNA_DA_PAGINA_INICIAL if estreita else COLUNA


CONTRASTE_TEXTO = 4.5
CONTRASTE_LINHA = 3.0
# Corpo efetivo mínimo do texto: o GitHub encolhe o SVG até caber na largura da página,
# então um diagrama largo demais vira letra miúda (15 px nominais vezes a escala).
FONTE_MINIMA = 14.0

PAGINA = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  html, body {{ margin: 0; background: {fundo}; }}
  #alvo {{ width: {largura}px; padding: 16px; box-sizing: content-box; }}
  /* elementsFromPoint só enxerga o que aceita ponteiro: a medição precisa das formas. */
  #alvo svg * {{ pointer-events: visiblePainted !important; }}
</style></head><body><div id="alvo"></div></body></html>"""

# O mermaid.initialize do bundle do GitHub (viewscreen.githubusercontent.com,
# mermaidMarkdown-*.js), com o tema escolhido pelo data-color-mode do iframe.
INICIALIZAR = """(modo) => {
  mermaid.initialize({
    startOnLoad: false,
    secure: ["secure", "securityLevel", "startOnLoad", "maxTextSize"],
    securityLevel: "antiscript",
    flowchart: { diagramPadding: 48 },
    gantt: { useWidth: 1200 },
    pie: { useWidth: 1200 },
    sequence: { diagramMarginY: 40 },
    theme: modo === "escuro" ? "dark" : "default",
  });
}"""

RENDERIZAR = """async ({fonte, id}) => {
  const alvo = document.getElementById("alvo");
  alvo.innerHTML = "";
  try {
    const { svg } = await mermaid.render(id, fonte);
    alvo.innerHTML = svg;
    return null;
  } catch (erro) {
    document.querySelectorAll(`[id^="${id}"], [id^="d${id}"]`).forEach((n) => n.remove());
    return String((erro && erro.message) || erro);
  }
}"""

# Toda a medição acontece no navegador: cores computadas, caixas renderizadas e o que
# está realmente pintado abaixo de cada texto.
MEDIR = r"""(fundoPagina) => {
  const svg = document.querySelector("#alvo svg");
  if (!svg) return { erro: "nenhum svg" };

  const rgba = (cor) => {
    if (!cor || cor === "none" || cor === "transparent") return null;
    let m = cor.match(/rgba?\(([^)]+)\)/);
    if (m) {
      const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    }
    m = cor.match(/^#([0-9a-f]{3,8})$/i);
    if (m) {
      let h = m[1];
      if (h.length <= 4) h = h.split("").map((c) => c + c).join("");
      const n = (i) => parseInt(h.slice(i, i + 2), 16);
      return [n(0), n(2), n(4), h.length === 8 ? n(6) / 255 : 1];
    }
    return null;
  };
  const sobre = (cima, baixo) => {
    const a = cima[3];
    return [0, 1, 2].map((i) => cima[i] * a + baixo[i] * (1 - a)).concat([1]);
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const contraste = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  const hex = (c) => "#" + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
  const pagina = rgba(fundoPagina);

  // A tinta de um elemento (preenchimento SVG ou fundo HTML), com opacidades.
  const tinta = (el) => {
    const s = getComputedStyle(el);
    if (el instanceof SVGElement) {
      if (["text", "tspan", "foreignObject", "svg", "g", "marker"].includes(el.tagName)) return null;
      let fill = s.fill;
      if (fill && fill.startsWith("url(")) {
        const id = fill.match(/#([^"')]+)/);
        const parada = id && document.getElementById(id[1])?.querySelector("stop");
        fill = parada ? getComputedStyle(parada).stopColor : null;
      }
      const c = rgba(fill);
      if (!c) return null;
      c[3] *= parseFloat(s.fillOpacity || "1") * parseFloat(s.opacity || "1");
      return c[3] > 0.02 ? c : null;
    }
    const c = rgba(s.backgroundColor);
    return c && c[3] > 0.02 ? c : null;
  };

  // A cor efetiva abaixo de um ponto: compõe as camadas pintadas, de baixo para cima.
  // Nada é ignorado de propósito: texto, <g> e foreignObject não pintam (tinta() devolve
  // null), e o fundo de um rótulo HTML (div.labelBkg, p) é exatamente a superfície dele.
  const superficie = (x, y) => {
    const camadas = [];
    for (const el of document.elementsFromPoint(x, y)) {
      if (el === document.body || el === document.documentElement) break;
      const c = tinta(el);
      if (c) { camadas.push(c); if (c[3] >= 0.99) break; }
    }
    let cor = pagina;
    for (const c of camadas.reverse()) cor = sobre(c, cor);
    return cor;
  };

  const problemas = [];
  const textos = [];
  const caixa = (el) => el.getBoundingClientRect();

  // Rótulos HTML (foreignObject) e de SVG puro (text), com a cor efetiva de cada um.
  const rotulos = [];
  svg.querySelectorAll("foreignObject").forEach((fo) => {
    const texto = fo.textContent.trim();
    if (!texto) return;
    const folha = [...fo.querySelectorAll("*")].reverse().find((e) => e.textContent.trim()) || fo;
    const cortado = folha.scrollWidth > fo.width.baseVal.value + 1.5 || folha.scrollHeight > fo.height.baseVal.value + 1.5;
    rotulos.push({ el: fo, texto, cor: rgba(getComputedStyle(folha).color), cortado });
  });
  svg.querySelectorAll("text").forEach((t) => {
    const texto = t.textContent.trim();
    if (!texto) return;
    const alvoCor = t.querySelector("tspan") || t;
    rotulos.push({ el: t, texto, cor: rgba(getComputedStyle(alvoCor).fill), cortado: false });
  });

  for (const r of rotulos) {
    const b = caixa(r.el);
    if (b.width < 1 || b.height < 1) continue;
    if (/<\/?[a-z][^>]*>/i.test(r.texto)) problemas.push(`tag HTML visível no rótulo "${r.texto}"`);
    if (r.cortado) problemas.push(`rótulo cortado: "${r.texto}"`);
    // Transborda a forma do nó que o contém?
    const no = r.el.closest("g.node, g.cluster, g.edgeLabel");
    const forma = no && no.querySelector(":scope > rect, :scope > path, :scope > polygon, :scope > circle, :scope > ellipse, :scope rect.basic, :scope > g > rect, :scope > g > path");
    if (forma && no.matches("g.node")) {
      const f = caixa(forma);
      if (b.left < f.left - 1.5 || b.right > f.right + 1.5 || b.top < f.top - 1.5 || b.bottom > f.bottom + 1.5)
        problemas.push(`rótulo transborda a forma: "${r.texto}"`);
    }
    if (!r.cor) continue;
    // O número do autonumber fica sobre um círculo desenhado como <marker>, que o
    // elementsFromPoint não enxerga: a superfície dele é o preenchimento do círculo.
    if (r.el.classList.contains("sequenceNumber")) {
      const circulo = svg.querySelector("marker[id$=sequencenumber] circle, marker[id*=sequencenumber] circle");
      const fundo = circulo && rgba(getComputedStyle(circulo).fill);
      if (fundo) {
        textos.push({ texto: r.texto, cor: hex(r.cor), fundo: hex(fundo), contraste: +contraste(r.cor, fundo).toFixed(2) });
        continue;
      }
    }
    const pontos = [[b.left + b.width / 2, b.top + b.height / 2], [b.left + 2, b.top + b.height / 2], [b.right - 2, b.top + b.height / 2]];
    let pior = Infinity, piorFundo = null;
    for (const [x, y] of pontos) {
      const fundo = superficie(x, y);
      const cor = r.cor[3] < 1 ? sobre(r.cor, fundo) : r.cor;
      const c = contraste(cor, fundo);
      if (c < pior) { pior = c; piorFundo = fundo; }
    }
    textos.push({ texto: r.texto, cor: hex(r.cor), fundo: hex(piorFundo), contraste: +pior.toFixed(2) });
  }

  // Linhas: arestas, mensagens, transições e linhas de vida, contra o fundo da página.
  const linhas = [];
  svg.querySelectorAll("path.flowchart-link, .edgePaths path, path.transition, line[class*=messageLine], path[class*=messageLine], line.actor-line, line[class^=actor-line]").forEach((l) => {
    const c = rgba(getComputedStyle(l).stroke);
    if (!c) return;
    const efetiva = c[3] < 1 ? sobre(c, pagina) : c;
    linhas.push({ cor: hex(c), contraste: +contraste(efetiva, pagina).toFixed(2) });
  });

  // Nós sobrepostos (formas de nós distintos que se cruzam).
  const nos = [...svg.querySelectorAll("g.node")].map((n) => ({ id: n.id, b: caixa(n) })).filter((n) => n.b.width > 0);
  for (let i = 0; i < nos.length; i++)
    for (let j = i + 1; j < nos.length; j++) {
      const a = nos[i].b, b = nos[j].b;
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 2 && h > 2) problemas.push(`nós sobrepostos: ${nos[i].id} e ${nos[j].id}`);
    }

  // A escala com que o GitHub desenha o SVG (largura 100%, max-width natural) e o menor
  // corpo de texto que o leitor vê depois dela.
  const s = caixa(svg);
  const natural = svg.viewBox.baseVal && svg.viewBox.baseVal.width ? svg.viewBox.baseVal.width : s.width;
  const escala = s.width / natural;
  const corpos = rotulos.map((r) => parseFloat(getComputedStyle(r.el.tagName === "foreignObject" ? (r.el.querySelector("*") || r.el) : r.el).fontSize)).filter((v) => v > 0);
  const fonte = corpos.length ? Math.min(...corpos) * escala : 0;
  return { problemas, textos, linhas, largura: Math.round(s.width), altura: Math.round(s.height),
           natural: Math.round(natural), escala: +escala.toFixed(3), fonte: +fonte.toFixed(1) };
}"""


@dataclass
class Medicao:
    """O que o leitor vê de um diagrama num modo de cor."""

    diagrama: Diagrama
    modo: str
    erro: str | None = None
    problemas: list[str] = field(default_factory=list)
    textos: list[dict[str, Any]] = field(default_factory=list)
    linhas: list[dict[str, Any]] = field(default_factory=list)
    largura: int = 0
    altura: int = 0
    natural: int = 0
    escala: float = 1.0
    fonte: float = 0.0
    captura: Path | None = None

    def falhas(self) -> list[str]:
        """Tudo o que reprova, com o diagrama e o modo para localizar."""
        onde = f"{self.diagrama.arquivo}#{self.diagrama.indice} ({self.modo})"
        if self.erro:
            return [f"{onde}: erro de render: {self.erro}"]
        falhas = [f"{onde}: {p}" for p in self.problemas]
        if self.fonte < FONTE_MINIMA:
            falhas.append(
                f"{onde}: texto a {self.fonte} px efetivos (mínimo {FONTE_MINIMA}): "
                f"{self.natural} px de largura natural encolhidos a {self.escala:.0%}"
            )
        falhas += [
            f'{onde}: texto "{t["texto"]}" {t["cor"]} sobre {t["fundo"]} = '
            f"{t['contraste']}:1 (mínimo {CONTRASTE_TEXTO})"
            for t in self.textos
            if t["contraste"] < CONTRASTE_TEXTO
        ]
        falhas += [
            f"{onde}: linha {linha['cor']} = {linha['contraste']}:1 contra o fundo "
            f"(mínimo {CONTRASTE_LINHA})"
            for linha in self.linhas
            if linha["contraste"] < CONTRASTE_LINHA
        ]
        return falhas


def medir(page: Page, diagrama: Diagrama, modo: str, saida: Path | None = None) -> Medicao:
    """Renderiza um diagrama num modo de cor e mede o resultado."""
    largura = coluna(diagrama)
    page.set_viewport_size({"width": largura + 32, "height": 900})
    page.set_content(PAGINA.format(fundo=FUNDOS[modo], largura=largura))
    page.add_script_tag(path=str(MERMAID_JS))
    page.evaluate(INICIALIZAR, modo)
    medicao = Medicao(diagrama, modo)
    medicao.erro = page.evaluate(RENDERIZAR, {"fonte": diagrama.fonte, "id": f"m{diagrama.indice}"})
    if medicao.erro:
        return medicao
    # elementsFromPoint só enxerga o que está na janela: ela cresce até caber o diagrama.
    altura = page.evaluate(
        "() => Math.ceil(document.getElementById('alvo').getBoundingClientRect().bottom)"
    )
    page.set_viewport_size({"width": largura + 32, "height": max(900, altura + 32)})
    resultado = page.evaluate(MEDIR, FUNDOS[modo])
    if "erro" in resultado:
        medicao.erro = resultado["erro"]
        return medicao
    medicao.problemas = resultado["problemas"]
    medicao.textos = resultado["textos"]
    medicao.linhas = resultado["linhas"]
    medicao.largura, medicao.altura = resultado["largura"], resultado["altura"]
    medicao.natural, medicao.escala, medicao.fonte = (
        resultado["natural"],
        resultado["escala"],
        resultado["fonte"],
    )
    if saida is not None:
        saida.mkdir(parents=True, exist_ok=True)
        medicao.captura = saida / f"{diagrama.id}-{modo}.png"
        page.locator("#alvo").screenshot(path=str(medicao.captura))
    return medicao


def main(argv: list[str]) -> int:
    """Mede todos os diagramas (ou os filtrados) e grava capturas e um relatório JSON."""
    from playwright.sync_api import sync_playwright

    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--saida", type=Path, required=True)
    args.add_argument("--filtro", default="", help="trecho do id do diagrama")
    args.add_argument("mmd", nargs="*", type=Path, help="arquivos .mmd avulsos (protótipos)")
    opcoes = args.parse_args(argv)
    alvos = [Diagrama(str(m), 0, 1, m.read_text(encoding="utf-8")) for m in opcoes.mmd] or [
        d for d in diagramas() if opcoes.filtro in d.id
    ]
    medicoes: list[Medicao] = []
    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch()
        page = navegador.new_page(
            viewport={"width": COLUNA + 32, "height": 900}, device_scale_factor=2
        )
        for diagrama in alvos:
            medicoes += [medir(page, diagrama, modo, opcoes.saida) for modo in FUNDOS]
        navegador.close()
    relatorio = [
        {
            "id": m.diagrama.id,
            "modo": m.modo,
            "falhas": m.falhas(),
            "natural": m.natural,
            "altura": m.altura,
            "escala": m.escala,
            "fonte": m.fonte,
            "textos": m.textos,
            "linhas": m.linhas,
        }
        for m in medicoes
    ]
    (opcoes.saida / "relatorio.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=1)
    )
    falhas = [f for m in medicoes for f in m.falhas()]
    sys.stdout.writelines(f"{falha}\n" for falha in falhas)
    sys.stdout.write(f"{len(medicoes)} renders, {len(falhas)} falhas; capturas em {opcoes.saida}\n")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
