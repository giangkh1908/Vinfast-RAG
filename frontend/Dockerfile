# ==============================================================================
# Multi-stage Production Dockerfile for Frontend (React + Vite SPA)
# ==============================================================================

# -- Stage 1: Build Frontend Assets --
FROM node:20-alpine AS builder

WORKDIR /app

# Cache dependencies
COPY package.json package-lock.json ./
RUN npm ci --prefer-offline

# Copy source code and build production bundle
COPY . .
RUN npm run build

# -- Stage 2: Serve with Lightweight NGINX Alpine (~25MB) --
FROM nginx:alpine-slim AS runner

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
