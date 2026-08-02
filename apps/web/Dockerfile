# syntax=docker/dockerfile:1.7

FROM node:22.23.0-alpine3.24 AS builder

WORKDIR /app

ENV NODE_OPTIONS="--max-old-space-size=1024"

ARG NPM_REGISTRY_PRIMARY="https://package-mirror.liara.ir/repository/npm/"
ARG NPM_REGISTRY_SECONDARY="https://mirror2.chabokan.net/npm/"
ARG NPM_REGISTRY_FALLBACK="https://registry.npmjs.org/"

# Keep dependency inputs in their own layer for BuildKit cache reuse.
COPY package.json package-lock.json .npmrc ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/ui/package.json ./packages/ui/package.json
COPY scripts/install-dependencies.sh ./scripts/install-dependencies.sh

RUN --mount=type=cache,id=nerkhbaan-web-npm,target=/root/.npm,sharing=locked \
    NPM_REGISTRY_PRIMARY="$NPM_REGISTRY_PRIMARY" \
    NPM_REGISTRY_SECONDARY="$NPM_REGISTRY_SECONDARY" \
    NPM_REGISTRY_FALLBACK="$NPM_REGISTRY_FALLBACK" \
    sh ./scripts/install-dependencies.sh && \
    test ! -d node_modules/electron && \
    test ! -d apps/web/node_modules/electron

COPY packages/ui ./packages/ui
COPY apps/web ./apps/web

RUN npm run build --workspace=nerkhbaan-web

FROM nginx:1.30.4-alpine3.24 AS runtime

RUN rm -rf /usr/share/nginx/html/*

COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
