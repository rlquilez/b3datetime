# Imagem do OWASP ZAP usada pelo DAST (job "DAST · OWASP ZAP"), fixada por versão e digest.
# Fica num Dockerfile — e não numa linha `docker run` do workflow — para o Dependabot
# (ecossistema docker, diretório /tests/dast) propor as versões novas.
FROM ghcr.io/zaproxy/zaproxy:2.17.0@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef

# Já é o usuário da imagem base; declarado para o Trivy (DS002) e o hadolint não
# suporem root. Ferramenta de varredura de vida curta: não há serviço a monitorar.
USER zap
HEALTHCHECK NONE
