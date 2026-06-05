# syntax=docker/dockerfile:1.7
# Multi-stage build для production frontend.
# Финальный образ — крошечный (статика на nginx-alpine), но в нашем
# prod-стеке мы используем его как «производитель статики»: при первом
# запуске копирует /usr/share/nginx/html → named volume, который монтирует Caddy.

# --- Stage 1: build ---
FROM node:22-alpine AS builder

WORKDIR /app

# Сначала только манифесты — для кеширования слоя npm install
COPY package.json package-lock.json ./
RUN npm ci

# Затем исходники
COPY . .

# Build → /app/dist
RUN npm run build


# --- Stage 2: dist artifact ---
# Используем nginx:alpine как базу (он крошечный, ~25 MB), но nginx
# здесь НЕ запускается — образ нужен только как контейнер с готовой
# статикой. docker-compose.prod.yml запускает его командой, которая
# копирует dist в /srv/frontend (общий named volume с Caddy) и выходит.
FROM nginx:1.27-alpine AS dist

COPY --from=builder /app/dist /usr/share/nginx/html

# Default command для prod: чистим shared volume от старых хешированных
# бандлов, копируем свежий dist и выходим.
CMD ["sh", "-c", "find /srv/frontend -mindepth 1 -delete 2>/dev/null; cp -r /usr/share/nginx/html/. /srv/frontend/ && echo 'frontend dist copied'"]
