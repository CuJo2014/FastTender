#!/bin/sh
# Снэпшот состояния FastTender каждые 5 минут.
# Помогает понять КОГДА именно случился инцидент с удалением контейнеров.
set -e
LOG=/home/master/fasttender/logs/state-snapshot.log
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Только наши контейнеры
CONTAINERS=$(docker ps -a --format "{{.Names}}={{.Status}}" 2>/dev/null | grep "^ft_prod_" | tr "\n" " " || echo "(none)")

# Размер postgres volume
VOLUME_SIZE="missing"
if docker volume inspect fasttender_postgres_data >/dev/null 2>&1; then
  VOLUME_SIZE=$(docker run --rm -v fasttender_postgres_data:/d alpine du -sh /d 2>/dev/null | cut -f1)
fi

# Количество строк в item (если postgres up)
ROWS="(postgres not running)"
if docker exec ft_prod_postgres pg_isready -U fasttender >/dev/null 2>&1; then
  ROWS=$(docker exec ft_prod_postgres psql -U fasttender -d fasttender -tA -c \
    "SELECT count(*) FILTER (WHERE is_active)||'/'||count(*) FROM item;" 2>/dev/null || echo "(query failed)")
fi

echo "${TS} containers=[${CONTAINERS}] volume_size=${VOLUME_SIZE} item_rows_active/total=${ROWS}" >> "$LOG"
