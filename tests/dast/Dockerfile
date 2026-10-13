# Imagem do OWASP ZAP usada pelo DAST (job "DAST · OWASP ZAP"), fixada por versão e digest.
# Fica num Dockerfile — e não numa linha `docker run` do workflow — para o Dependabot
# (ecossistema docker, diretório /tests/dast) propor as versões novas.
FROM ghcr.io/zaproxy/zaproxy:2.17.0@sha256:7aaa659b0d43078febd82e29bad112285c370727e86ab8340444220e17d9f0d2

# Já é o usuário da imagem base (`zap`, uid/gid 1000); declarado para o Trivy (DS002)
# não supor root, e numérico pelo hadolint (DL3066). Ferramenta de varredura de vida
# curta: não há serviço a monitorar.
USER 1000:1000
HEALTHCHECK NONE
