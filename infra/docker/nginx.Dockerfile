# syntax=docker/dockerfile:1.10
# Nginx «Думыча»: прокси API, голосового канала (WebSocket) и панель администратора (статика).
#   docker build -f infra/docker/nginx.Dockerfile -t doomich/nginx .
ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.30-alpine

FROM ${NODE_IMAGE} AS admin
WORKDIR /admin
COPY apps/admin/package.json apps/admin/package-lock.json ./
# сеть с подменой TLS-сертификатов: docker build --secret id=ca_bundle,src=/путь/ca-bundle.crt ...
RUN --mount=type=cache,target=/root/.npm --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi; \
    npm ci --no-audit --no-fund
COPY apps/admin/ ./
RUN npm run build

FROM ${NGINX_IMAGE}
RUN rm -f /etc/nginx/conf.d/default.conf
COPY infra/nginx/doomich /etc/nginx/doomich
COPY infra/nginx/templates /etc/nginx/templates
COPY infra/nginx/templates-prod /etc/nginx/templates-prod
COPY --from=admin /admin/dist /usr/share/nginx/admin
# имя сервера по умолчанию; в боевом режиме задайте DOOMICH_SERVER_NAME и NGINX_ENVSUBST_TEMPLATE_DIR
ENV DOOMICH_SERVER_NAME=_
