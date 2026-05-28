# syntax=docker/dockerfile:1.7
# Multi-stage build на uv (раздел 13.6 — Docker как стандарт)

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Системные пакеты (минимум)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# uv ставим из официального образа — фиксированная версия
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

# Сначала — только манифесты, для кеша слоя зависимостей
COPY pyproject.toml ./
COPY README.md ./

# Устанавливаем зависимости (без проекта — для кеширования)
RUN uv sync --no-install-project --extra dev

# Копируем исходники
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

# Дотягиваем сам пакет
RUN uv sync --extra dev

# Каталог для загрузок
RUN mkdir -p /var/lib/fasttender/uploads

EXPOSE 8000

# Команды переопределяются в docker-compose для разных ролей (app / worker / migrations)
CMD ["uvicorn", "fasttender.main:app", "--host", "0.0.0.0", "--port", "8000"]
