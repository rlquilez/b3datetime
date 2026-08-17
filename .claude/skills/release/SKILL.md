---
name: release
description: Publica uma nova versão do b3datetime — escolhe o número SemVer, atualiza o CHANGELOG.md no formato Keep a Changelog, sincroniza a versão nos arquivos que a duplicam, cria a tag e publica a página de Releases do GitHub. Use quando for lançar uma versão, atualizar o CHANGELOG, criar uma tag, ou quando o usuário pedir "release", "nova versão", "publicar versão" ou "atualizar o changelog".
---

# Release do b3datetime

Convenção: **[SemVer](https://semver.org/lang/pt-BR/)** + **[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)**, tudo em pt-BR.

## 1. Escolha do número

`MAJOR.MINOR.PATCH`. A pergunta que decide é **"um cliente existente precisa mudar alguma coisa?"**

| Incremento | Quando | Exemplos reais deste projeto |
|---|---|---|
| **MAJOR** | Quebra de contrato observável da API | Endpoint passa a devolver 404 onde devolvia 503; `/v1/health` passa a devolver 503 onde devolvia 200; um range antes aceito passa a ser rejeitado com 400; campo removido ou renomeado na resposta |
| **MINOR** | Funcionalidade nova, retrocompatível | Novo endpoint; novo campo opcional na resposta; novo parâmetro opcional de query |
| **PATCH** | Correção sem mudar contrato | Corrigir cálculo interno; corrigir vazamento de credencial em log; performance; dependências |

Regras que evitam erro:

- **Mudança de status HTTP é MAJOR**, mesmo quando o status antigo estava errado. Orquestradores, retries e clientes reagem a código de status.
- **Corrigir uma resposta errada para uma rejeição explícita é MAJOR.** Devolver 400 onde antes vinha `200 []` muda o contrato, ainda que o `[]` fosse mentira.
- **Tornar a correção opcional via flag não rebaixa o incremento** se o *default* muda. O que conta é o comportamento padrão.
- Corrigir comportamento que nunca foi documentado nem observável de fora é PATCH.

## 2. Fonte da verdade da versão

`src/config.py` → `api_version`. É a única fonte; todos os outros lugares são cópias que precisam ser sincronizadas na mesma leva:

| Lugar | O que atualizar |
|---|---|
| `src/config.py` | `api_version: str = "X.Y.Z"` |
| `README.md` | a versão citada no exemplo de resposta de `GET /` |
| `CHANGELOG.md` | nova seção `## [X.Y.Z] - AAAA-MM-DD` |
| tag git | `vX.Y.Z` (com o `v`; a tag é a única forma que leva prefixo) |

`.github/workflows/release.yml` **impõe** essa sincronia: o job `verify` reprova a tag se `${GITHUB_REF_NAME#v}` divergir de `api_version` ou da versão do README. Se o job reprovar, o erro é real — corrija a fonte, não o workflow.

## 3. Formato do CHANGELOG

```markdown
# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não publicado]

## [2.0.0] - 2026-08-17

### Alterado

- **BREAKING** `/v1/health` retorna 503 quando o estado é `unhealthy`. (#7)

### Corrigido

- `cp .env.example .env` não impede mais o boot. (#5)

### Adicionado

- Endpoint `GET /v1/calendar-info`. (#6)

### Segurança

- URL do Redis deixa de ser logada com credenciais. (#10)
```

Seções, sempre em pt-BR e **nesta ordem** quando presentes: `Adicionado`, `Alterado`, `Descontinuado`, `Removido`, `Corrigido`, `Segurança`.

Regras de escrita:

- Uma entrada por mudança **perceptível pelo usuário da API**. Refatoração interna sem efeito externo não entra.
- Toda entrada quebra-compatibilidade começa com **`**BREAKING**`** e vai em `Alterado`.
- Referencie a Issue com `(#N)`.
- Escreva do ponto de vista de quem consome a API, não de quem editou o arquivo. "`/v1/hours` devolve 404 quando a chave não existe no Redis" — não "corrigido `get_value` em `redis_service.py`".
- Mantenha uma seção `## [Não publicado]` no topo para acumular entre releases.

## 4. Passos

```bash
# 1. Versão nova em src/config.py e README.md sincronizados
# 2. Seção do CHANGELOG escrita, com a data de hoje

# 3. Commit
git add -A
git commit -m "chore(release): v2.0.0

Refs #11"

# 4. Tag e push
git tag -a v2.0.0 -m "v2.0.0"
git push origin main
git push origin v2.0.0
```

O push da tag dispara `release.yml`, que valida a sincronia, extrai a seção do CHANGELOG, retagueia a imagem Docker (`2`, `2.0`, `2.0.0`) e cria a página de Release.

Se o workflow não estiver disponível, o equivalente manual:

```bash
awk -v v="2.0.0" '$0 ~ "^## \\["v"\\]" {f=1; next} f && /^## \[/ {exit} f' CHANGELOG.md > /tmp/release-notes.md
gh release create v2.0.0 --title "v2.0.0" --notes-file /tmp/release-notes.md
```

## 5. Antes de publicar, confirme

- [ ] O incremento corresponde à maior mudança do lote (uma quebra num lote de dez correções ainda é MAJOR).
- [ ] `api_version`, README e CHANGELOG dizem o mesmo número.
- [ ] A data da seção é a data real da publicação.
- [ ] Toda entrada `**BREAKING**` tem guia de migração no README.
- [ ] O CI da `main` está verde e o quality gate passou — não se marca release sobre commit vermelho, e o `retag` do `release.yml` exige que a imagem `sha-<curto>` daquele commit exista no registry.
- [ ] Toda Issue incluída na release foi fechada com o comentário detalhado que o fluxo exige.
