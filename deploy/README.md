# Production deployment (Phase 1)

Стек поднимается одной командой `docker compose` с Caddy в роли HTTPS-фронта.
Раздел 5.3, 5.4, 13.6 архитектурного документа.

## Архитектура

```
[Internet] ──HTTPS──> [Caddy:443]
                          │
                          ├── /api/*, /health* ──> [FastAPI: app:8000]
                          │                          └── postgres + redis (internal)
                          │                          └── celery worker (internal)
                          │
                          └── /*       ──> static (frontend dist)
```

Только Caddy слушает внешний трафик (порты 80, 443). Остальные сервисы
доступны только внутри docker network.

## Предусловия

1. **VPS** — Linux (Ubuntu 22.04+ / Debian 12+ / любой современный). Минимум
   2 vCPU, 4 GB RAM, 20 GB SSD. Открытые порты: 22 (SSH), 80, 443.

2. **Docker + Docker Compose plugin** на сервере.

3. **DNS** — A-запись `DOMAIN → IP-сервера` должна резолвиться **до** запуска,
   иначе Let's Encrypt не выдаст сертификат (rate limit на провалы).

## Деплой за 7 шагов

```bash
# 1. Клонировать репозиторий
git clone git@github.com:CuJo2014/FastTender.git
cd FastTender

# 2. Сгенерировать Basic Auth credentials (запиши пароль!)
./deploy/bootstrap.sh basic-auth

# 3. Скопировать и заполнить .env.prod
cp deploy/.env.prod.example .env.prod
$EDITOR .env.prod
#   DOMAIN=fasttender.your-domain.tld
#   CADDY_EMAIL=admin@your-domain.tld
#   BASIC_AUTH_HASH=<из шага 2>
#   POSTGRES_PASSWORD=<свой сильный>

# 4. Проверить prereqs (docker, dns, порты)
./deploy/bootstrap.sh check-prereqs

# 5. Собрать и запустить
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# 6. Подождать ~30 секунд, посмотреть логи Caddy на запрос Let's Encrypt
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f caddy

# 7. Открыть https://DOMAIN в браузере
```

## Обновление

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
# migrations service применит alembic upgrade head автоматически перед стартом app
```

## Бэкапы

Postgres-дамп через утилиту:

```bash
./deploy/bootstrap.sh backup-db        # → backups/fasttender_<ts>.sql.gz
./deploy/bootstrap.sh restore-db backups/fasttender_<ts>.sql.gz
```

Рекомендуется cron-job раз в сутки + копия в S3/Y-Object/любое внешнее хранилище.

## Что внутри .env.prod

| Переменная | Назначение | Чувствительность |
|---|---|---|
| `DOMAIN` | Hostname для TLS | — |
| `CADDY_EMAIL` | Для Let's Encrypt | низкая |
| `BASIC_AUTH_USER` / `BASIC_AUTH_HASH` | Защита всего UI | **высокая** |
| `POSTGRES_PASSWORD` | Пароль БД | **критичная** |
| `UVICORN_WORKERS` / `CELERY_CONCURRENCY` | Тюнинг под VPS | — |

Файл `.env.prod` исключён из git через `.gitignore`. Никогда не коммить.

## Troubleshooting

**Caddy не получает сертификат:**
- Проверь `docker logs ft_prod_caddy` — будет сказано почему.
- Чаще всего DNS не указывает на сервер. `dig +short $DOMAIN A` должен вернуть IP сервера.
- Если переключаешься между staging/prod Let's Encrypt — удали `docker volume rm fasttender_caddy_data` и перезапусти.

**HTTP 502 от Caddy:**
- `docker compose ... logs app` — приложение не стартануло, обычно из-за БД.
- Проверь `docker compose ... ps` что postgres и app в `Up (healthy)`.

**Воркер не подхватывает задачи:**
- `docker logs ft_prod_worker` — обычно Redis не доступен или imports не подхватились.
- Проверь что в `core/celery_app.py` `include` содержит актуальные модули задач.

**После git pull не подхватились изменения миграций:**
- Сервис `migrations` запускается one-shot и `restart: "no"`. После pull сделай:
  `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build migrations`
  чтобы прокатить миграции, потом перезапусти `app` и `worker`.

## On-premise vs облако

Эта схема одинаковая для облака и on-premise. Различия — только в IP+DNS и
наличии firewall'а провайдера. Раздел 5.4 архитектуры.
