# Imagem multi-stage da B3 DateTime API.
# Stage 1: build das dependências
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: runtime
FROM python:3.11-slim

# Patches de segurança do sistema disponíveis no momento do build. A imagem base
# costuma ficar atrás dos repositórios Debian (ex.: CVE-2026-53615 na família
# util-linux), e sem este passo o Trivy reprova o build por vulnerabilidade
# herdada e já corrigida upstream.
RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Usuário sem privilégios. O container rodava como root, o que o Trivy sinaliza
# como misconfiguração e amplia o impacto de qualquer execução indevida de código.
RUN groupadd --system --gid 1001 app && \
    useradd --system --uid 1001 --gid app --create-home --home-dir /home/app app

WORKDIR /app

# Remove o ferramental de build da imagem de runtime. pip, setuptools e wheel não
# são usados em execução — o uvicorn e as dependências vêm de /home/app/.local — e
# são fonte recorrente de CVE de severidade alta herdada da imagem base
# (CVE-2026-24049 em wheel e CVE-2026-23949 em jaraco.context, ambas apontadas
# pelo Trivy). Removê-los resolve a classe do problema em vez de perseguir versão,
# reduz a superfície de ataque e impede `pip install` dentro de um container
# comprometido.
RUN python -m pip uninstall -y pip setuptools wheel 2>/dev/null || true; \
    rm -rf /usr/local/lib/python3.11/site-packages/pip* \
           /usr/local/lib/python3.11/site-packages/setuptools* \
           /usr/local/lib/python3.11/site-packages/wheel* \
           /usr/local/lib/python3.11/site-packages/pkg_resources \
           /usr/local/lib/python3.11/site-packages/_distutils_hack \
           /usr/local/lib/python3.11/site-packages/distutils-precedence.pth \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.11

COPY --from=builder --chown=app:app /root/.local /home/app/.local
COPY --chown=app:app src/ ./src/

ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

EXPOSE 8000

# O endpoint responde 503 quando o estado é unhealthy, e urlopen levanta em
# não-2xx — é essa combinação que permite ao Docker marcar o container como
# unhealthy. Enquanto /v1/health respondia 200 em todos os estados, este
# HEALTHCHECK não tinha como falhar nunca.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health')" || exit 1

# --proxy-headers e --forwarded-allow-ips: atrás do Kong em outro host, o default
# (127.0.0.1) faz o uvicorn descartar X-Forwarded-Proto/For. O efeito é url_for e
# os 307 de redirect_slashes emitirem http:// num site HTTPS, e todo log de acesso
# registrar o IP do proxy em vez do cliente.
CMD ["uvicorn", "src.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
