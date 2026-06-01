# Disaster Recovery — восстановление FastTender на новом сервере

Сценарий: упал сервер, диск восстановить нельзя, нужно поднять FastTender
на новом VPS с минимальным простоем. **Цель — рабочая система за ~1 час.**

Допущения:
- Есть доступ к **GitHub** (исходники) и **Google Drive** (бэкап БД +
  `.env.prod`)
- DNS управляется отдельно (Cloudflare/регистратор) и может быть
  перенаправлен на новый IP

## Что где находится

| Что | Где | Восстановление |
|---|---|---|
| Исходники | GitHub `CuJo2014/FastTender` | `git clone` |
| БД-дамп | `gdrive:FastTender-Backups/fasttender_YYYYMMDD-HHMMSS.sql.gz` (90 дней) | `rclone copy` + `restore-db` |
| `.env.prod` | `gdrive:FastTender-Backups/config/.env.prod` | `rclone copy` |
| LE сертификаты | Не бэкапятся | Caddy перевыпустит автоматически |
| Maksmart БД | `gdrive:Maksmart-Backups/maksmart_*.sql.gz` | Через docker exec pg_dump (см. ниже) |

## Шаги восстановления (60 минут)

### 1. Новый VPS (5 мин)

Поднять Ubuntu 22.04+ с публичным IP. Минимум 4 GB RAM, 50 GB диска.

```bash
# Создать пользователя master с sudo (если не root):
sudo adduser master && sudo usermod -aG sudo,docker master
```

### 2. Установка зависимостей (10 мин)

```bash
sudo apt update && sudo apt install -y curl git unzip
# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER  # logout/login после этого
# rclone (для бэкапов)
mkdir -p ~/.local/bin && cd /tmp
curl -fsSL -o rclone.zip https://downloads.rclone.org/rclone-current-linux-amd64.zip
unzip -q rclone.zip && cp rclone-*/rclone ~/.local/bin/ && chmod +x ~/.local/bin/rclone
rm -rf rclone.zip rclone-*
```

### 3. Получить rclone-токен к Drive (5 мин)

**Это проблема курицы и яйца**: токен на упавшем сервере, нужен чтобы
скачать бэкап. **Обход**: скачать бэкап через веб-интерфейс Drive в
браузере (drive.google.com → папка `FastTender-Backups` → скачать
последний `.sql.gz` и `config/.env.prod`).

После того как бэкап на новом сервере — заново настроить rclone для
последующих автобэкапов:

```bash
~/.local/bin/rclone authorize "drive"
# Открыть URL в браузере (через SSH-tunnel: ssh -L 53682:127.0.0.1:53682)
# Скопировать токен в ~/.config/rclone/rclone.conf:
mkdir -p ~/.config/rclone
cat > ~/.config/rclone/rclone.conf <<EOF
[gdrive]
type = drive
scope = drive
token = <JSON-токен>
EOF
chmod 600 ~/.config/rclone/rclone.conf
```

### 4. Клон репозитория и конфиг (5 мин)

```bash
cd ~ && git clone https://github.com/CuJo2014/FastTender.git fasttender
cd fasttender

# Положить .env.prod (скачанный из Drive)
cp /tmp/.env.prod ./.env.prod  # из шага 3
chmod 600 .env.prod
```

### 5. Билд образов + миграции (15 мин)

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod build app worker frontend-build migrations

# Поднять postgres + redis
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d postgres redis

# Дождаться healthy
docker exec ft_prod_postgres pg_isready -U fasttender  # ждать пока ok
```

### 6. Восстановить БД (10 мин)

```bash
# Положить SQL-дамп
cp /tmp/fasttender_*.sql.gz ./backups/
ls -la backups/

# Restore (потребует подтверждения)
./deploy/bootstrap.sh restore-db backups/fasttender_YYYYMMDD-HHMMSS.sql.gz

# Проверка
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "
SELECT count(*) AS items FROM item WHERE is_active;"
# Должно быть ~133000 (или сколько было на момент бэкапа)
```

### 7. Старт остальных сервисов + DNS (10 мин)

```bash
# Применить миграции (на случай если БД отстаёт от схемы)
PG_PASS=$(grep '^POSTGRES_PASSWORD' .env.prod | cut -d= -f2)
docker run --rm --network fasttender_default \
  -e FT_DATABASE_URL_SYNC="postgresql+psycopg://fasttender:${PG_PASS}@postgres:5432/fasttender" \
  -e FT_DATABASE_URL="postgresql+asyncpg://fasttender:${PG_PASS}@postgres:5432/fasttender" \
  fasttender-migrations:latest uv run alembic upgrade head

# Поднять app + worker + caddy
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d app worker caddy
```

**DNS:** в админке домена сменить A-запись `fasttender.arsenalpro.tech`
на новый IP. Caddy при первом обращении перевыпустит LE-сертификат
автоматически (нужно 30-60 сек после распространения DNS).

Проверка:
```bash
curl -I https://fasttender.arsenalpro.tech/api/v1/healthz
# Ожидается: 401 (Basic Auth) или 200
```

### 8. Восстановить cron (5 мин)

```bash
# Бэкап-cron + диагностика + monitoring
crontab -e
# Добавить:
@reboot setsid sh -c "/home/master/fasttender/deploy/events-monitor.sh" > /dev/null 2>&1 < /dev/null
15 4 * * * /usr/sbin/logrotate -s /home/master/fasttender/logs/.logrotate.state /home/master/fasttender/.config/logrotate/fasttender.conf >> /home/master/fasttender/logs/logrotate.log 2>&1
*/5 * * * * /home/master/fasttender/deploy/state-snapshot.sh
0 3 * * * /home/master/fasttender/deploy/backup-cron.sh >> /home/master/fasttender/logs/backup.log 2>&1
# (Если был maksmart):
# 30 3 * * * /home/master/scripts/maksmart-backup-cron.sh >> /home/master/maksmart-backups/backup.log 2>&1

# Запустить events monitor немедленно (без ребута)
mkdir -p /home/master/fasttender/logs
nohup setsid sh -c "/home/master/fasttender/deploy/events-monitor.sh" > /dev/null 2>&1 < /dev/null &
```

## Что потеряется

- **До 24 часов работы** между последним бэкапом и падением сервера
- **Celery in-flight задачи** (несколько импортов нужно перезапустить)
- **Старые сертификаты LE** (но перевыпускаются автоматически)
- **Логи диагностики** (`logs/*.log`) — если важны, бэкапить отдельно

## Восстановление Maksmart

Отдельный процесс (maksmart не в этом репо). Шаги:
1. Клон maksmart репо (если есть на git)
2. Скачать дамп с `gdrive:Maksmart-Backups/`
3. Восстановить через `docker exec -i maksmart-postgres-1 psql -U maksmart Maksmart < dump.sql`
4. Поставить backup-cron из `/home/master/scripts/maksmart-backup-cron.sh` (скрипт не в git, скопировать с другого источника или восстановить из бэкапа)

## Тестовый прогон (рекомендация)

Раз в квартал — провести **dry-run восстановления** на тестовом VPS
чтобы убедиться что процедура актуальна. Особенно после крупных
изменений (новые миграции, новые volumes, новые env-переменные).

Дата последнего прогона: ~~_не было_~~
