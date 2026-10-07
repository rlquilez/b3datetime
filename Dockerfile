# Imagem multi-stage da B3 DateTime API.
# Python 3.14 é a única versão do projeto: runtime da imagem, requires-python, alvo do
# ruff e do mypy, sonar.python.version e o job de testes do CI.
#
# Base Alpine oficial, fixada por digest; o Dependabot propõe o digest novo a cada
# semana e o PR passa pelo CI antes de ser adotado. A python:3.14-slim trazia o
# userland Debian inteiro (perl, util-linux, apt, pam, login, tar, ncurses) que a
# aplicação nunca executa: eram 173 alertas do Trivy no code scanning, 150 deles
# sem correção no Debian (#39). Todas as dependências compiladas (numpy, pandas,
# pydantic-core, uvloop, httptools, watchfiles, websockets, PyYAML) publicam wheels
# musllinux para cp314, então o build não precisa de compilador.
# A tag é 3.14-alpine, e não 3.14-alpineX.Y: quando a imagem oficial muda de
# release do Alpine, a troca chega como PR de digest em vez de a tag fixada parar
# de receber atualizações em silêncio.

# Stage 1: build das dependências
FROM python:3.14-alpine@sha256:9e9fde4d32eedce0b661d9ab91e826b62dddf28e928c230ec55f1866cac66b01 AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: runtime
FROM python:3.14-alpine@sha256:9e9fde4d32eedce0b661d9ab91e826b62dddf28e928c230ec55f1866cac66b01 AS runtime

# Usuário sem privilégios. O container rodava como root, o que o Trivy sinaliza
# como misconfiguração e amplia o impacto de qualquer execução indevida de código.
# uid/gid 1001, os mesmos da época da base Debian.
RUN addgroup -S -g 1001 app && \
    adduser -S -D -u 1001 -G app -h /home/app app

WORKDIR /app

# Remove o ferramental de build da imagem de runtime. pip, setuptools e wheel não
# são usados em execução — o uvicorn e as dependências vêm de /home/app/.local — e
# são fonte recorrente de CVE de severidade alta herdada da imagem base
# (CVE-2026-24049 em wheel e CVE-2026-23949 em jaraco.context, ambas apontadas
# pelo Trivy). Removê-los resolve a classe do problema em vez de perseguir versão,
# reduz a superfície de ataque e impede `pip install` dentro de um container
# comprometido.
# O diretório de site-packages vem do sysconfig, e não de um caminho com a versão
# hardcoded: um bump de Python deixava o rm sem efeito e o pip de volta na imagem.
RUN python -m pip uninstall -y pip setuptools wheel 2>/dev/null || true; \
    SITE="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" && \
    rm -rf "$SITE"/pip* "$SITE"/setuptools* "$SITE"/wheel* "$SITE"/pkg_resources \
           "$SITE"/_distutils_hack "$SITE"/distutils-precedence.pth \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.*

COPY --from=builder --chown=app:app /root/.local /home/app/.local

# Patches de segurança publicados depois do digest fixado. O CI passa um
# APK_REFRESH novo a cada run (run_id-run_attempt), o que invalida o cache só a
# partir daqui. Com a base Debian, o `apt-get upgrade` equivalente vinha do cache do
# GitHub Actions enquanto o digest da base não mudava: os patches nunca entravam e
# o Trivy bloqueante passou a reprovar todo build (#39). As dependências ficam na
# camada anterior e continuam em cache. Qualquer RUN adicionado depois deste ARG
# também é refeito a cada run.
ARG APK_REFRESH=local
RUN echo "apk upgrade (APK_REFRESH=${APK_REFRESH})" && \
    apk upgrade --no-cache

# Layout src: o pacote vive em src/b3datetime/ no repositório e em /app/b3datetime na
# imagem. O uvicorn põe o diretório de trabalho (/app) no sys.path (--app-dir ".").
COPY --chown=app:app src/b3datetime/ ./b3datetime/

ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Commit do build, exposto em `GET /` (campo `build`): é como o CI confirma, de fora,
# que a produção já serve a imagem que ele acabou de publicar. Depois do último RUN,
# para não invalidar camada nenhuma: muda a cada commit e só custa esta linha.
ARG BUILD_SHA=local
ENV APP_BUILD=${BUILD_SHA}

# UID:GID numéricos, e não o nome: o Kubernetes só consegue verificar `runAsNonRoot`
# com um UID numérico (hadolint DL3066). São os do usuário `app` criado acima.
USER 1001:1001

EXPOSE 8000

# O endpoint responde 503 quando o estado é unhealthy, e urlopen levanta em
# não-2xx — é essa combinação que permite ao Docker marcar o container como
# unhealthy. Enquanto /v1/health respondia 200 em todos os estados, este
# HEALTHCHECK não tinha como falhar nunca.
# Forma exec (JSON), sem shell (hadolint DL3025): o Python sai com código 1 quando o
# urlopen levanta, que é exatamente o "unhealthy" do Docker — o `|| exit 1` da forma
# shell era redundante.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health')"]

# --proxy-headers e --forwarded-allow-ips: atrás do Kong em outro host, o default
# (127.0.0.1) faz o uvicorn descartar X-Forwarded-Proto/For. O efeito é url_for e
# os 307 de redirect_slashes emitirem http:// num site HTTPS, e todo log de acesso
# registrar o IP do proxy em vez do cliente.
# --factory: não há `app` de módulo; o uvicorn chama `create_app()` (ler o ambiente e o
# `.env` no `import` violava a invariante "nenhum I/O no import").
CMD ["uvicorn", "b3datetime.main:create_app", "--factory", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
