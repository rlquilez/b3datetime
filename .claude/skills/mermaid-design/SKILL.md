---
name: mermaid-design
description: Design system "Neo Editorial / Soft Minimal" dos diagramas Mermaid do b3datetime — config canônico por tipo, paleta por papel com contraste validado nos modos claro e escuro do GitHub, regras de layout que cabem na página, fidelidade à arquitetura real e o fluxo de verificação (Agentic Mermaid + render fiel ao GitHub no Chromium). Use ao criar, editar ou revisar qualquer bloco ```mermaid em .md do repositório, ao mexer em tests/docs, ou quando o usuário pedir "diagrama", "Mermaid", "fluxograma", "diagrama de sequência", "melhorar o visual dos diagramas".
---

# Diagramas Mermaid do b3datetime

Todo bloco ```` ```mermaid ```` de todo `.md` rastreado (hoje 13, em `README.md` e
`tests/README.md`) e os modelos em `modelos/` seguem esta skill. O job de CI
**`Documentação · diagramas`** (`tests/docs`) a impõe: um diagrama fora do padrão reprova o
pipeline e nada é publicado.

Na prática: **copie um modelo de `modelos/`**, troque o conteúdo, rode a verificação
local (seção 8) e revise as capturas nos dois modos de cor.

## 1. Princípios

1. **Legível onde é lido.** O leitor vê o diagrama no GitHub, em claro *ou* escuro, numa
   coluna de ~1000 px. O que não funciona lá não funciona.
2. **Tudo rastreia ao código.** Cada caixa e cada seta existe no código, no `ci.yml` ou
   na infraestrutura documentada. Agrupamento visual (subgrafo) não inventa relação.
3. **Hierarquia por tipografia, não por enfeite.** Título em negrito, subtítulo curto.
   Sem ícone, emoji, numeração decorativa ou HTML.
4. **A cor diz o papel.** Cada papel (entrada, gateway, aplicação principal, serviço,
   dados, externo, gate) tem uma cor fixa, igual em todos os diagramas.
5. **Menos é mais.** Até ~15 nós. Um diagrama maior vira visão geral + detalhe.
6. **Verificado, não suposto.** Todo diagrama passa pelo gate antes do push. A prova
   final é o GitHub de verdade.

## 2. O renderizador do GitHub

Fatos verificados no bundle do iframe (`viewscreen.githubusercontent.com`) em 2026-10-07.
Eles mudam sem aviso, então **reverifique antes de confiar**:

```bash
F=$(curl -sL 'https://viewscreen.githubusercontent.com/markdown/mermaid?docs_host=https%3A%2F%2Fdocs.github.com' \
      | grep -oE '/static/assets/mermaidMarkdown-[^"]+\.js' | head -1)
curl -sL "https://viewscreen.githubusercontent.com$F" -o bundle.js
grep -c usecaseSystemBoundary bundle.js   # >0: Mermaid ≥ 12.0
grep -c orientFeedbackEdges bundle.js     # >0: Mermaid ≥ 12.1
grep -o 'mermaid.initialize([^)]*)' bundle.js | head -1
```

- **A versão é o Mermaid 12.1.x.** `tests/docs/package.json` fixa `mermaid@12.1.0`. Quando
  o GitHub mudar de versão, atualize esse pin, nunca antes. O Dependabot propõe; quem
  decide é o marcador no bundle.
- **No 12, o ELK é o layout padrão e `look: neo` é o padrão do flowchart.** Validar em
  outra versão foi o erro que produziu os diagramas antigos: eles foram aprovados no
  11.4 + dagre, e o GitHub desenhava outra coisa.
- **O `initialize` do GitHub** é `securityLevel: "antiscript"`, `theme` igual a
  `"dark"` ou `"default"` conforme o modo de cor, `flowchart.diagramPadding: 48` e
  `sequence.diagramMarginY: 40`. A lista `secure` trava só `secure`, `securityLevel`,
  `startOnLoad` e `maxTextSize`. **O frontmatter do diagrama vence todo o resto**: tema,
  `themeVariables`, `look`, `layout`, `flowchart.*` e `themeCSS`.
- **Fundo do iframe: `#ffffff` no claro e `#0d1117` no escuro.** O CSS do GitHub não
  recolore o texto do diagrama. Uma paleta clara fixa (`theme: base`) é desenhada sobre
  `#0d1117` no modo escuro. Daí a **regra dual**: todo texto fica sobre uma superfície
  pintada pelo próprio diagrama (nó, subgrafo, fundo do rótulo da aresta, nota, painel), e
  toda linha tem ≥ 3:1 nos dois fundos.
- **O SVG encolhe até caber na largura.** Um diagrama com 2200 px de largura natural sai
  a 44% e o texto de 15 px vira 6,6 px. O gate exige corpo efetivo ≥ 13 px numa coluna
  de 1012 px, o que dá largura natural ≤ ~1170 px. A meta é ≤ 1000 px.
- **O `themeCSS` passa por um sanitizador que descarta o CSS inteiro se houver `<` ou
  `>`.** Então nada de seletor filho (`a > b`).
- **O Mermaid deixa o fundo do rótulo de aresta a 50% de opacidade**
  (`.edgeLabel rect { opacity: .5 }`), o que dá 2,9:1 no escuro. O `themeCSS` canônico
  devolve 100%.

## 3. Config canônico

Sempre **frontmatter YAML** (`---\nconfig: …\n---`), nunca `%%{init}%%`, que está
obsoleto e perde para o frontmatter. Copie de `modelos/`: o bloco é longo e o teste
`test_frontmatter_canonico` compara **chave por chave** com `tests/docs/design.py`.

| Tipo | Modelo | Pontos que não são óbvios |
|---|---|---|
| `flowchart` | `arquitetura.mmd`, `pipeline.mmd` | `htmlLabels: false` na **raiz** (o `flowchart.htmlLabels` é ignorado nos nós do 12) · `fontFamily` também na raiz (só no `themeVariables` o texto saía em Times) · `nodeBorder` definido (sem ele, o `neo` desenha borda em gradiente) · `wrappingWidth: 400` (o padrão de 120 px quebra todo rótulo) · `themeCSS` com rótulo de aresta opaco e arestas de 1,5 px |
| `stateDiagram-v2` | `estados.mmd` | `htmlLabels: true` (com `false`, o nome do estado sai alinhado à esquerda) · `themeCSS` pinta de branco o fundo HTML do rótulo da transição |
| `sequenceDiagram` | `sequencia.mmd` | painel `rect rgb(248, 250, 252)` envolvendo **todas** as mensagens (o texto da mensagem não tem fundo próprio) · `themeCSS` com halo (`paint-order: stroke`, 12 px) que apaga a linha de vida sob o texto · `mirrorActors: false` · sem `autonumber` (o círculo dá 3,04:1) |

Ajustes livres por diagrama (`tests/docs/design.py::AJUSTES`): `layout` (`dagre` ou
`elk`), `flowchart.nodeSpacing`/`rankSpacing` (10–90), `flowchart.wrappingWidth`
(200–800) e `sequence.actorMargin` (30–90). O resto é fixo.

**Dagre é o padrão**: curvas `basis` suaves e respeito ao `direction` dos subgrafos. No
ELK do 12.1, uma aresta correu colada à borda de um subgrafo. Use ELK só se o render
mostrar menos cruzamentos, e registre o motivo.

## 4. Paleta por papel

"Soft Minimal" com o mínimo de ajuste para contraste. Texto ≥ 4,5:1 sobre a superfície
pintada e linhas ≥ 3:1 nos dois fundos, medidos no Chromium pelo gate. Fonte única:
`tests/docs/design.py`.

| Papel (`classDef`) | Uso | Fundo | Borda | Texto |
|---|---|---|---|---|
| `entrada` | cliente, ponto de entrada, passo manual | `#FFFFFF` | `#DCE4EC` 1,5 px | `#334155` |
| `gateway` | Kong, borda, controle estático | `#F8FAFD` | `#B9CBDF` 1,5 px | `#344C68` |
| `principal` | a aplicação, o artefato central | `#E8F7F2` | `#0F9F87` **2,5 px** | `#075E50` |
| `servico` | módulos e serviços internos | `#FFFFFF` | `#B9DCD1` 1,5 px | `#356C60` |
| `dados` | Redis, cache, métricas, gates de qualidade | `#FFFAF4` | `#E6CEB1` 1,5 px | `#8B623C` |
| `externo` | fora do repo, secundário, produção | `#FFFFFF` | `#DCE4EC` 1,5 px | `#64748B` |
| `gate` | portão binário (`ci-ok`, limiares) | `#FFFFFF` | `#334155` 2 px | `#334155` |
| `falha` | estado de falha | `#FDF3F4` | `#EBC4CB` 1,5 px | `#9B3B4D` |
| `saudavel` / `degradado` | estados do health | `#E8F7F2` / `#FFFAF4` | `#0F9F87` 2 px / `#E6CEB1` | `#075E50` / `#8B623C` |

| Subgrafo (`style <id>`) | Fundo | Borda | Título |
|---|---|---|---|
| `container` (aplicação, fases de execução) | `#F8FCFA` | `#C8E5DA` | `#257361` |
| `estatica` (análise estática, passos manuais) | `#F8FAFD` | `#B9CBDF` | `#344C68` |
| `consolidacao` | `#FFFAF4` | `#E6CEB1` | `#8B623C` |

**Ajustes de contraste (original → ajustado).** Só um foi necessário: conexões
`#94A3B8` → **`#8895A9`** (2,56:1 → 3,07:1 no `#ffffff`, 7,0:1 no `#0d1117`). As demais
cores do prompt original passaram como estavam. `gate` e `falha` são papéis novos,
derivados das famílias de tom existentes, com texto ≥ 7:1.

## 5. Geometria e tipografia

- **Rótulo = título em negrito + subtítulo**, numa markdown string:
  ```text
  api("`**FastAPI / Uvicorn**
  --proxy-headers`")
  ```
  A quebra de linha é real (newline), sem `<br>` e sem tag de negrito.
- **Linhas curtas**: ≤ ~30 caracteres no comum e **64 no máximo** (o gate reprova
  acima). No máximo 3 linhas por nó.
- **Nada de `__` dentro de markdown string**: `__main__` vira "main" em negrito, e
  nenhum escape funciona no GitHub (`\_` e `&#95;` falham). Reescreva ("Entrada do
  pacote") ou use um rótulo simples entre aspas.
- **`<br>` é a única tag**, só em rótulo simples (aspas sem crase) e em estados.
  `<i>`, `<b>` e `<code>` aparecem literais no GitHub.
- **Nós arredondados** `("…")` como padrão. Cilindro `[(…)]` só para armazenamento.
  Losango `{…}` só para decisão real, de uma linha (com duas fica enorme no `neo`).
  Cápsula `([…])` para `gate`. Hexágono não, porque fica largo demais no `neo`.
- **Transição de estado ≤ 28 caracteres**: o rótulo HTML quebra em ~200 px.

## 6. Layout que cabe

- **Prefira `TB`.** `LR` só com ≤ 4 colunas e rótulos curtos: cada coluna custa
  ~250 px.
- **Arestas entre subgrafos vão para o subgrafo** (`estatica --> consolidacao`), não
  para um nó de dentro. Uma aresta de fora para um nó interno faz o dagre **ignorar o
  `direction` do subgrafo**.
- **O `direction` de um subgrafo é relativo ao eixo.** Num pai `TB`, um subgrafo
  `direction LR` com nós soltos os **empilha** (todos ficam no mesmo rank, e o rank é
  horizontal). Um `direction TB` os põe **lado a lado**. Subgrafo sem `direction`
  explícito alterna em relação ao pai.
- **Grade 2×N:** num subgrafo `direction LR`, cadeias invisíveis de dois (`a ~~~ b`,
  `c ~~~ d`) viram linhas de uma grade. Os nós de cada coluna centralizam, então mantenha
  larguras parecidas. Um nó solto cai na **última** coluna; para levá-lo à primeira,
  ligue-o invisivelmente a um nó da segunda (`mut ~~~ sonar`).
- **Pirâmide:** nós em cadeia invisível `TB`, com o texto crescendo ~9 caracteres por
  camada, `rankSpacing` ~10 e `wrappingWidth` ~600 (`tests/README.md`, "Pirâmide").
- **`~~~` é só layout.** Não conta como relação na revisão de fidelidade. E **nada de
  `linkStyle default`**, que torna visíveis os elos invisíveis: a espessura das arestas
  vem do `themeCSS`.
- **Rótulo de aresta curto** (`HTTPS`, `MGET`, `sim`). Uma frase vira subtítulo do nó.

## 7. Fidelidade ao b3datetime

O que os diagramas de arquitetura afirmam, e de onde vem:

- **Kong Gateway na frente**, rota `/b3datetime`, `strip_path: true` por padrão. O
  `ROOT_PATH=/b3datetime` vai para a aplicação. O endereço interno do upstream **nunca**
  aparece.
- **FastAPI + Uvicorn num container** (`--proxy-headers`), com **cache local de TTL 1 h**
  e o **calendário BVMF em processo** (`exchange_calendars`, sem I/O de rede).
- **A API lê do Redis com `MGET`.** Quem escreve (`SET`) é um **sistema externo, fora
  deste repositório**. Nunca desenhe a API escrevendo no Redis.
- **Camadas** (import-linter): `__main__ > main > routers > dependencies > services >
  config`. `main` monta `middleware`, `documentacao` (que serve `static/`) e os routers,
  e constrói os services no `lifespan`.
- **`/v1/health`**: `healthy` e `degraded` são 200, `unhealthy` é 503.
- **CI:** o grafo de `needs` de `.github/workflows/ci.yml`. Para conferir:
  `python -c "import yaml; [print(k, v.get('needs')) for k, v in yaml.safe_load(open('.github/workflows/ci.yml'))['jobs'].items()]"`.
- **Sem autenticação em produção**: nenhum diagrama mostra `apikey` como obrigatória.

Todo redesenho compara os fatos antes e depois com `am describe --format facts`
(seção 8). Relação perdida ou inventada só entra se for intencional, e isso fica
registrado no commit.

## 8. Fluxo de trabalho

No formato do [Agentic Mermaid](https://agentic-mermaid.dev/start.md): canal local,
capacidades lidas antes de autorar, verificação estrutural e leitura semântica de volta.
Depois vem o que o Agentic não cobre: o render fiel ao GitHub.

1. **Ferramentas** (uma vez): `cd tests/docs && npm ci`, depois `pip install -r
   requirements-browser.txt && python -m playwright install --only-shell chromium`.
   Node ≥ 22.
2. **Partir de um modelo** (`modelos/*.mmd`) e fixar os fatos de antes, se houver
   diagrama antigo:
   `tests/docs/node_modules/.bin/am describe --format facts antigo.mmd > antes.txt`.
3. **Gate local**, o mesmo do CI:
   ```bash
   python -m pytest tests/docs -m "not e2e" --no-cov                # estático + Agentic + render
   python -m tests.docs.renderizador --saida /tmp/capturas         # só o render, com capturas e relatorio.json
   python -m tests.docs.renderizador --saida /tmp/c rascunho.mmd   # um protótipo avulso
   ```
   O `relatorio.json` traz, por diagrama e modo, a largura natural, a escala, o corpo
   efetivo e o contraste de cada texto e de cada linha.
4. **Agentic Mermaid** (`tests/docs/agentic.py`): `am verify` recebe o diagrama
   convertido por `para_agentic`. Markdown string vira rótulo simples (senão o `am`
   marca o fluxograma inteiro como **opaco** e "passa" sem modelar nada), o `themeCSS`
   sai (o modo seguro recusa CSS cru com `RENDER_FAILED`) e o painel da sequência também
   (tudo dentro dele é opaco). Tolerados: `INEFFECTIVE_CONFIG` (campos que só o mermaid.js
   usa) e `UNSUPPORTED_SYNTAX` `sequence_opaque_segment` (blocos `alt`). Qualquer outro
   aviso reprova, inclusive `LABEL_OVERFLOW` (limite de 64), `GROUP_BREACH` e
   `LOW_CONTRAST`. Os estilos do Agentic (hand-drawn, temas próprios) **não** valem no
   GitHub.
5. **Fatos depois**: `am describe --format facts` sobre o diagrama convertido e
   comparação com `antes.txt` **por rótulo**, porque os ids mudam.
6. **Revisar as capturas**, as duas de cada diagrama. O gate pega contraste, corte e
   escala, mas não pega feiura: cruzamentos, colunas desalinhadas, espaço morto,
   hierarquia confusa.
7. **GitHub real, depois do push**: abrir `README.md` e `tests/README.md` no github.com
   em modo anônimo, claro e escuro (Playwright com `color_scheme`), e conferir cada
   iframe de diagrama. É a única prova de que a versão e o `initialize` não mudaram.

## 9. Checklist de aceite

- [ ] Frontmatter canônico do tipo, copiado de um modelo; ajustes só nos campos de
      `AJUSTES`.
- [ ] Todo nó com papel (`class …`) e todo subgrafo com `style` da paleta; nenhuma cor
      fora de `design.py`.
- [ ] Rótulos: negrito + subtítulo, ≤ 64 caracteres por linha, ≤ 3 linhas, sem `__`, sem
      tag além de `<br>`, sem emoji.
- [ ] Largura natural ≤ ~1000 px (o `relatorio.json` mostra `natural` e `fonte`).
- [ ] Sequência: painel `rect` em volta de tudo, sem `autonumber`.
- [ ] Fatos iguais aos de antes, ou mudança intencional registrada.
- [ ] Gate local verde: `pytest tests/docs -m "not e2e" --no-cov`.
- [ ] As duas capturas revisadas, e o GitHub real conferido nos dois modos.

## 10. Antipadrões vistos neste repositório

| Antipadrão | O que acontecia |
|---|---|
| Validar com outra versão do Mermaid | Aprovado no 11.4 + dagre, desenhado pelo 12.1 + ELK: rótulos cortados no GitHub |
| `wrappingWidth` como remendo | Escondia o problema real (rótulo longo demais) e voltava a cortar em outro diagrama |
| LR com 7+ colunas | Largura natural de 2200 px, texto a 6,6 px |
| `%%{init}%%` + `<i>` + emoji | Configuração inconsistente, tags literais, ruído |
| Texto direto sobre o fundo do iframe | No modo escuro: `#cccccc` sobre `#585858` (2,x:1) |
| `__main__` em markdown string | "main" em negrito, sem escape que funcione |
| `themeCSS` com `>` | O sanitizador descartou o CSS inteiro, sem erro |
| `linkStyle default` com `~~~` | Os elos invisíveis da pirâmide apareceram |
| Aresta de fora para nó interno do subgrafo | O `direction` do subgrafo foi ignorado |
| Nota (`note right of`) no stateDiagram em TB | A nota caiu longe do estado, com uma linha pontilhada longa; o código HTTP agora fica dentro do estado (`state "healthy<br>HTTP 200" as healthy`) |
| `autonumber` | O círculo do número com 3,04:1 |
| Confiar no `am verify` com markdown string | Diagrama "opaco": `ok: true` sem nenhum nó modelado |

## 11. Referências

- Agentic Mermaid: guia para agentes (https://agentic-mermaid.dev/start.md) e pacote
  `agentic-mermaid` no npm (https://www.npmjs.com/package/agentic-mermaid).
- Mermaid, *Theming* (só o tema `base` aceita `themeVariables`, só hex é reconhecido):
  https://mermaid.js.org/config/theming.html
- Mermaid, *Configuration* (frontmatter, precedência, `secure`):
  https://mermaid.js.org/config/configuration.html
- Mermaid, *Flowchart*, markdown strings, formas e `direction` em subgrafos:
  https://mermaid.js.org/syntax/flowchart.html
- Notas de versão do Mermaid (12.0: ELK padrão e `neo`):
  https://github.com/mermaid-js/mermaid/releases
- GitHub Docs, *Creating diagrams*:
  https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams
- `ekroon/github-mermaid-diagrams` (renderizar claro e escuro antes de publicar; tags
  literais): https://github.com/ekroon/github-mermaid-diagrams
- `mpurbo/mermaid-pastel-style` (papéis fixos, texto escuro sobre pastel, fundo do
  rótulo de aresta): https://github.com/mpurbo/mermaid-pastel-style
- WCAG 2.2: contraste de texto 4,5:1 (https://www.w3.org/TR/WCAG22/#contrast-minimum) e
  de elementos não textuais 3:1 (https://www.w3.org/TR/WCAG22/#non-text-contrast).

Onde uma referência contradiz o código do GitHub (por exemplo, "o modo escuro força
texto claro"), vale o código, reverificado como na seção 2.
