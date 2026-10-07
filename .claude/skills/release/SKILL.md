---
name: release
description: Publica uma nova versão do b3datetime — escolhe o número SemVer, atualiza o CHANGELOG.md no formato Keep a Changelog, sincroniza a versão nos arquivos que a duplicam e confere a tag, as tags da imagem e a página de Releases que o CI publica sozinho a partir do commit de release. Use quando for lançar uma versão, atualizar o CHANGELOG, criar uma tag, ou quando o usuário pedir "release", "nova versão", "publicar versão" ou "atualizar o changelog".
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

O job **`Contrato · oasdiff`** do CI torna a regra do MAJOR executável: ele compara `tests/contract/openapi.json` com o snapshot da última release e **reprova breaking change no contrato se o MAJOR não subiu**. Como todo push na `main` vai para produção, a quebra e o bump chegam no mesmo push. Ele não substitui o julgamento abaixo: mudança de status HTTP ou de semântica sem mudança de schema não aparece no diff.

Regras que evitam erro:

- **Mudança de status HTTP é MAJOR**, mesmo quando o status antigo estava errado. Orquestradores, retries e clientes reagem a código de status.
- **Corrigir uma resposta errada para uma rejeição explícita é MAJOR.** Devolver 400 onde antes vinha `200 []` muda o contrato, ainda que o `[]` fosse mentira.
- **Tornar a correção opcional via flag não rebaixa o incremento** se o *default* muda. O que conta é o comportamento padrão.
- Corrigir comportamento que nunca foi documentado nem observável de fora é PATCH.

## 2. Fonte da verdade da versão

`src/b3datetime/config.py` → `api_version`. É a única fonte; todos os outros lugares são cópias que precisam ser sincronizadas na mesma leva:

| Lugar | O que atualizar |
|---|---|
| `src/b3datetime/config.py` | `api_version: str = "X.Y.Z"` |
| `pyproject.toml` | `version = "X.Y.Z"` em `[project]` |
| `README.md` | a linha `<strong>Versão atual: X.Y.Z</strong>` do cabeçalho (é o que o teste de sincronia procura); o exemplo de `GET /` na seção de endpoints também cita a versão |
| `CHANGELOG.md` | nova seção `## [X.Y.Z] - AAAA-MM-DD` e os links de comparação no rodapé |
| `tests/contract/openapi.json` | o snapshot do contrato traz `info.version`: regenere com `PYTHONPATH=src python scripts/gerar_openapi.py` |
| tag git | **não se cria à mão**: o job `release` do CI cria `vX.Y.Z` (com o `v`, a única forma que leva prefixo) no commit de release |

Os testes de `tests/unit/test_config.py` **impõem** essa sincronia no CI, antes de qualquer publicação (e `tests/api/test_openapi.py::test_snapshot_do_contrato_esta_em_dia` impõe o snapshot):

- `test_versao_sincronizada_com_pyproject`: `pyproject.toml` igual a `api_version`;
- `test_versao_sincronizada_com_readme_e_changelog`: README com `Versão atual: X.Y.Z` e CHANGELOG com `## [X.Y.Z] - AAAA-MM-DD`;
- `test_secao_do_changelog_da_versao_atual_nao_vazia`: a seção tem conteúdo. É ela que vira as notas da Release, e o job `release` reprovaria só depois de o `latest` já ter sido publicado.

Se algum deles reprovar, o erro é real — corrija a fonte, não o teste.

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
# 1. Versão nova em src/b3datetime/config.py, pyproject.toml e README.md sincronizados
#    e o snapshot do contrato regenerado: PYTHONPATH=src python scripts/gerar_openapi.py
# 2. Seção do CHANGELOG escrita, com a data de hoje, e links de comparação atualizados

# 3. Commit e push da main — e só. Nenhuma tag à mão.
git add -A
git commit -m "chore(release): v2.0.0

Refs #11"
git push origin main

# 4. Acompanhe o CI do commit de release (o job `release` roda depois do docker-publish)
gh run watch "$(gh run list --workflow CI --branch main --limit 5 --json databaseId,headSha \
  --jq "[.[] | select(.headSha==\"$(git rev-parse HEAD)\")][0].databaseId")" --exit-status

# 5. Confira o que o CI publicou
gh release view v2.0.0                       # notas = seção [2.0.0] do CHANGELOG
git ls-remote origin 'refs/tags/v2.0.0'      # tag no commit de release
```

O job `release` do `ci.yml` roda depois do `docker-publish` em todo push na `main`. Quando a `api_version` do commit ainda não tem Release, ele:

1. cria a tag `vX.Y.Z` naquele commit (pela API; tag leve);
2. adiciona `X.Y.Z`, `X.Y` e `X` (só `X.Y.Z` em pré-release) ao manifest multi-arch que o `docker-publish` **acabou** de enviar, pelo digest e com `crane tag`, **sem rebuild**;
3. publica a Release com a seção do CHANGELOG como notas (`--prerelease` quando a versão tem `-`).

Em qualquer outro push, a versão já tem Release e o job não faz nada. Não existe mais ordem a respeitar entre CI e tag: tudo acontece no mesmo run, e o digest é o daquele commit.

Se o job `release` falhar no meio, use **"Re-run failed jobs"** no run do commit de release: todos os passos são idempotentes e o digest do `docker-publish` é preservado. Ele reprova de propósito em dois casos, e aí o erro é real:

- a consulta à Release falhou por outro motivo que não `release not found` — uma falha passageira da API não pode mover tags;
- já existe uma tag `vX.Y.Z` apontando para **outro** commit.

Em último caso, sem CI, só a página de Release pode ser feita à mão. As tags da imagem exigem as credenciais do registry, que só o CI tem. O recorte é o mesmo do `awk` do job e de `test_secao_do_changelog_da_versao_atual_nao_vazia`, mas escrito em Python, porque o carregador de skills substitui o `$0` do `awk` pelos argumentos da invocação e deixaria o comando errado na tela.

```bash
python3 - 2.0.0 > /tmp/release-notes.md <<'PY'
import re, sys
versao = sys.argv[1]
changelog = open("CHANGELOG.md", encoding="utf-8").read()
secao = re.search(rf"^## \[{re.escape(versao)}\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
print(secao.group(1).strip())
PY
gh release create v2.0.0 --target "$(git rev-parse HEAD)" --title "v2.0.0" --notes-file /tmp/release-notes.md
```

## 5. Antes de publicar, confirme

- [ ] O incremento corresponde à maior mudança do lote (uma quebra num lote de dez correções ainda é MAJOR).
- [ ] `api_version`, README e CHANGELOG dizem o mesmo número.
- [ ] A data da seção é a data real da publicação.
- [ ] Toda entrada `**BREAKING**` tem guia de migração no README.
- [ ] O CI do commit de release ficou verde, com o quality gate aprovado, e o job `release` publicou a tag, as tags da imagem e a Release (`gh release view vX.Y.Z`). Um commit vermelho não publica nada, e portanto não gera release.
- [ ] Toda Issue incluída na release foi fechada com o comentário detalhado que o fluxo exige.
