# Imagem do k6 usada pelo job "Performance · k6", fixada por versão e digest.
# Fica num Dockerfile — e não numa linha `docker run` do workflow — para o Dependabot
# (ecossistema docker, diretório /tests/load) propor as versões novas.
FROM grafana/k6:2.3.0@sha256:2dd4756ec6e14e62778916e1eb850108e4b499304c02df56760fa0bdb0fba0b8

# Já é o usuário da imagem base (`k6`, uid/gid 12345); declarado para o Trivy (DS002)
# não supor root, e numérico pelo hadolint (DL3066). Ferramenta de carga de vida curta:
# não há serviço a monitorar.
USER 12345:12345
HEALTHCHECK NONE
