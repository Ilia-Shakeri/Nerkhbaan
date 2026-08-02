# syntax=docker/dockerfile:1.7

FROM node:22.23.0-alpine3.24 AS builder

WORKDIR /app
ENV NODE_OPTIONS="--max-old-space-size=768"

ARG NPM_REGISTRY_PRIMARY="https://package-mirror.liara.ir/repository/npm/"
ARG NPM_REGISTRY_SECONDARY="https://mirror2.chabokan.net/npm/"
ARG NPM_REGISTRY_FALLBACK="https://registry.npmjs.org/"

COPY package.json package-lock.json .npmrc ./
COPY apps/admin-web/package.json ./apps/admin-web/package.json

RUN --mount=type=cache,id=nerkhbaan-admin-npm,target=/root/.npm,sharing=locked \
    set -eu; \
    install_status=1; \
    for registry in \
        "$NPM_REGISTRY_PRIMARY" \
        "$NPM_REGISTRY_SECONDARY" \
        "$NPM_REGISTRY_FALLBACK"; do \
        echo "Trying npm registry: $registry"; \
        if npm ci \
            --workspace=nerkhbaan-admin-web \
            --include-workspace-root=false \
            --registry="$registry" \
            --no-audit \
            --no-fund; then \
            install_status=0; \
            break; \
        fi; \
    done; \
    test "$install_status" -eq 0; \
    test ! -d node_modules/electron; \
    test ! -d apps/admin-web/node_modules/electron

COPY apps/admin-web ./apps/admin-web
RUN npm run build --workspace=nerkhbaan-admin-web

FROM nginx:1.30.4-alpine3.24 AS runtime

RUN rm -rf /usr/share/nginx/html/*
COPY apps/admin-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/apps/admin-web/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
