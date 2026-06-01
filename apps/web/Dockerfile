# Stage 1: Build the Vite + React application
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./

# Mount the npm cache to avoid re-downloading packages from mirrors on every single build
# NPM FALLBACK CHAIN for high availability
RUN --mount=type=cache,target=/root/.npm \
    npm install --registry="https://package-mirror.liara.ir/repository/npm/" || \
    npm install --registry="https://registry.npmmirror.com" || \
    npm install --registry="https://registry.npm.ir" || \
    npm install --registry="https://npm.farakav.com" || \
    npm install --registry="https://mirror-npm.runflare.com" || \
    npm install --registry="https://registry.npmjs.org"

# Copy source code and build for production
COPY . .
RUN npm run build

# Stage 2: Serve the application using Nginx
FROM nginx:alpine

# Remove default Nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy the custom Nginx configuration for React Router
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy the built assets from the builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
