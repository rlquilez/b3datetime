# Imagem do k6 usada pelo job "Performance · k6", fixada por versão e digest.
# Fica num Dockerfile — e não numa linha `docker run` do workflow — para o Dependabot
# (ecossistema docker, diretório /tests/load) propor as versões novas.
FROM grafana/k6:2.3.0@sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34

# Já é o usuário da imagem base (`k6`, uid/gid 12345); declarado para o Trivy (DS002)
# não supor root, e numérico pelo hadolint (DL3066). Ferramenta de carga de vida curta:
# não há serviço a monitorar.
USER 12345:12345
HEALTHCHECK NONE
