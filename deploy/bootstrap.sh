#!/usr/bin/env bash
# Утилита для деплоя FastTender (Phase 1).
#
# Использование:
#   ./deploy/bootstrap.sh basic-auth        # сгенерировать Basic Auth credentials
#   ./deploy/bootstrap.sh check-prereqs     # проверить docker, dns, swap
#   ./deploy/bootstrap.sh backup-db         # дамп postgres в ./backups/
#   ./deploy/bootstrap.sh restore-db FILE   # восстановить из дампа

set -euo pipefail

CMD="${1:-help}"
shift || true

case "$CMD" in
  basic-auth)
    # Генерируем сильный пароль 24 символа + bcrypt-хеш через caddy:alpine
    USER="${1:-fasttender}"
    PASSWORD="$(head -c 18 /dev/urandom | base64 | tr -d '+/=' | head -c 24)"
    echo "Generating bcrypt hash..." >&2
    HASH="$(docker run --rm caddy:2-alpine caddy hash-password --plaintext "$PASSWORD" 2>/dev/null)"
    # Для docker-compose --env-file нужно эскейпить $ как $$, иначе compose
    # пытается интерполировать `$2a`, `$14`, ... как переменные.
    HASH_ESCAPED="$(printf '%s' "$HASH" | sed 's/\$/$$/g')"

    cat <<EOF

Basic Auth credentials:
  user:     $USER
  password: $PASSWORD
  bcrypt:   $HASH

Скопируй в .env.prod (значение хеша уже с эскейпленными \$\$ под docker compose):
  BASIC_AUTH_USER=$USER
  BASIC_AUTH_HASH=$HASH_ESCAPED

Сохрани пароль (полностью) в надёжном месте — после деплоя его уже не достать.
EOF
    ;;

  check-prereqs)
    echo "=== Docker ==="
    docker --version || { echo "Docker не установлен"; exit 1; }
    docker compose version || { echo "Docker Compose plugin не установлен"; exit 1; }

    echo ""
    echo "=== DNS ==="
    if [ -f .env.prod ]; then
        # shellcheck source=/dev/null
        source .env.prod
        if [ -n "${DOMAIN:-}" ]; then
            EXPECTED_IP="$(curl -fsS ifconfig.me 2>/dev/null || echo unknown)"
            ACTUAL="$(dig +short @1.1.1.1 "$DOMAIN" A | head -1)"
            echo "  $DOMAIN → $ACTUAL"
            echo "  IP сервера: $EXPECTED_IP"
            if [ "$ACTUAL" != "$EXPECTED_IP" ]; then
                echo "  ⚠ Несовпадение. Let's Encrypt НЕ сможет выдать серт."
            else
                echo "  ✓ DNS совпадает"
            fi
        fi
    else
        echo "  .env.prod не найден — пропускаю DNS-проверку"
    fi

    echo ""
    echo "=== Свободное место ==="
    df -h / | tail -1

    echo ""
    echo "=== Свободная память + swap ==="
    free -h | head -3

    echo ""
    echo "=== Порты 80, 443 ==="
    ss -tlnp 2>/dev/null | grep -E ':80\s|:443\s' || echo "  свободны"
    ;;

  backup-db)
    OUT="./backups/fasttender_$(date -u +%Y%m%d-%H%M%S).sql.gz"
    mkdir -p ./backups
    echo "→ $OUT"
    docker compose -f docker-compose.prod.yml --env-file .env.prod \
        exec -T postgres pg_dump -U "${POSTGRES_USER:-fasttender}" "${POSTGRES_DB:-fasttender}" \
        | gzip > "$OUT"
    echo "OK: $(ls -lh "$OUT" | awk '{print $5}')"
    ;;

  restore-db)
    FILE="${1:?Usage: bootstrap.sh restore-db FILE.sql.gz}"
    test -f "$FILE" || { echo "Файл не найден: $FILE"; exit 1; }
    echo "⚠ Это перезапишет текущую БД. Ctrl-C если не уверен. 5 сек..."
    sleep 5
    gunzip -c "$FILE" | docker compose -f docker-compose.prod.yml --env-file .env.prod \
        exec -T postgres psql -U "${POSTGRES_USER:-fasttender}" "${POSTGRES_DB:-fasttender}"
    ;;

  help|*)
    sed -n '1,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \?//'
    ;;
esac
