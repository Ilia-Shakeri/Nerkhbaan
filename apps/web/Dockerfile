# Stage 1: Build the Vite + React application
FROM node:20-alpine AS builder

WORKDIR /app

# Copy root and workspace package files first to leverage Docker layer caching
COPY package.json package-lock.json* ./
COPY packages/ui/package.json ./packages/ui/
COPY apps/web/package.json ./apps/web/

# Find and replace all dead Runflare URLs in the lockfile with the Liara mirror.
# This prevents npm from attempting to download from the dead links hardcoded in the lockfile.
RUN if [ -f package-lock.json ]; then \
        sed -i 's|https://mirror-npm.runflare.com|https://package-mirror.liara.ir/repository/npm|g' package-lock.json; \
    fi

# Mount the npm cache to avoid re-downloading packages from mirrors on every single build.
# We use npm install with a fallback chain for maximum reliability.
RUN --mount=type=cache,target=/root/.npm \
    npm config set registry https://package-mirror.liara.ir/repository/npm/ && \
    npm install --no-audit --no-fund || \
    (npm config set registry https://registry.npmmirror.com && npm install --no-audit --no-fund) || \
    (npm config set registry https://registry.npmjs.org && npm install --no-audit --no-fund)

# Copy the actual source code for UI package and the Web app
COPY packages/ui ./packages/ui
COPY apps/web ./apps/web

# Build the application
WORKDIR /app/apps/web
RUN npm run build

# Stage 2: Serve the application using Nginx
FROM nginx:alpine

# Remove default Nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy the custom Nginx configuration for React Router (relative to build context root)
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf

# Copy the built assets from the builder stage
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
