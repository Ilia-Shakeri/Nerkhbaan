# syntax=docker/dockerfile:1.7
FROM node:22.23.0-alpine3.24 AS public_builder
WORKDIR /app
ENV NODE_OPTIONS="--max-old-space-size=1024"
ARG NPM_REGISTRY_PRIMARY="https://package-mirror.liara.ir/repository/npm/"
ARG NPM_REGISTRY_SECONDARY="https://mirror2.chabokan.net/npm/"
ARG NPM_REGISTRY_FALLBACK="https://registry.npmjs.org/"
COPY package.json package-lock.json .npmrc ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/ui/package.json ./packages/ui/package.json
COPY scripts/install-dependencies.sh ./scripts/install-dependencies.sh
RUN --mount=type=cache,id=nerkhbaan-web-npm,target=/root/.npm,sharing=locked \
    sh ./scripts/install-dependencies.sh && test ! -d node_modules/electron
COPY packages/ui ./packages/ui
COPY apps/web ./apps/web
ARG VITE_VAPID_PUBLIC_KEY=""
ENV VITE_VAPID_PUBLIC_KEY=$VITE_VAPID_PUBLIC_KEY
RUN npm run build --workspace=nerkhbaan-web

FROM node:22.23.0-alpine3.24 AS admin_builder
WORKDIR /app
ENV NODE_OPTIONS="--max-old-space-size=768"
ARG NPM_REGISTRY_PRIMARY="https://package-mirror.liara.ir/repository/npm/"
ARG NPM_REGISTRY_SECONDARY="https://mirror2.chabokan.net/npm/"
ARG NPM_REGISTRY_FALLBACK="https://registry.npmjs.org/"
COPY package.json package-lock.json .npmrc ./
COPY apps/admin-web/package.json ./apps/admin-web/package.json
RUN --mount=type=cache,id=nerkhbaan-admin-npm,target=/root/.npm,sharing=locked \
    set -eu; installed=0; \
    for registry in "$NPM_REGISTRY_PRIMARY" "$NPM_REGISTRY_SECONDARY" "$NPM_REGISTRY_FALLBACK"; do \
      if npm ci --workspace=nerkhbaan-admin-web --include-workspace-root=false --registry="$registry" --no-audit --no-fund; then installed=1; break; fi; \
    done; test "$installed" = 1; test ! -d node_modules/electron
COPY apps/admin-web ./apps/admin-web
ENV VITE_ADMIN_BASE_PATH=/admin/
RUN npm run build --workspace=nerkhbaan-admin-web

FROM nginx:1.30.6-alpine3.24
RUN apk upgrade --no-cache
COPY --from=public_builder /app/apps/web/dist /usr/share/nginx/html/public
COPY --from=admin_builder /app/apps/admin-web/dist /usr/share/nginx/html/public/admin
COPY --from=admin_builder /app/apps/admin-web/dist /usr/share/nginx/html/admin/admin
COPY apps/web/security-headers.conf /etc/nginx/public-security.inc
COPY apps/admin-web/security-headers.conf /etc/nginx/admin-security.inc
COPY nginx/single/nginx.conf.template /etc/nginx/single.conf.template
COPY nginx/single/proxy-common.inc /etc/nginx/proxy-common.inc
COPY nginx/single/entrypoint.sh /usr/local/bin/single-web-start
RUN chmod 755 /usr/local/bin/single-web-start
USER nginx
EXPOSE 8080
ENTRYPOINT ["sh", "/usr/local/bin/single-web-start"]
