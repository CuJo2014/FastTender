# Операционные команды FastTender

Рабочие команды для типичных задач сопровождения. Все выполняются
на VPS (`/home/master/fasttender/`).

## Чистка деактивированных позиций

При каждом REPLACE-импорте importer помечает старые позиции
`is_active = false` (физически не удаляет — есть истории матчей).
Со временем накапливается «мусор» от перезагрузок прайсов.

Безопасно удалить все deactivated позиции (на матчинг не влияют —
там везде фильтр `is_active = true`):

```bash
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "DELETE FROM item WHERE NOT is_active;"
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "VACUUM ANALYZE item;"
```

**Важно:** `VACUUM` нельзя в одной транзакции с `DELETE` — psql ругнётся
«cannot run inside a transaction block». Поэтому две отдельные команды.

Проверить результат:

```bash
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "
SELECT s.name,
  (SELECT count(*) FROM item WHERE source_id = ds.id AND is_active) AS active,
  (SELECT count(*) FROM item WHERE source_id = ds.id AND NOT is_active) AS inactive
FROM supplier s
JOIN data_source ds ON ds.supplier_id = s.id
ORDER BY s.created_at;
"
```

## Сброс кэша column_mapping у поставщика

Importer кэширует найденный маппинг колонок в `data_source.config`,
чтобы при следующем импорте применить тот же шаблон. Если шаблон
оказался неудачным (попало не то поле), а парсер уже исправлен —
сброс заставит re-detect:

```bash
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "
UPDATE data_source SET config = '{}'::jsonb
WHERE id = (SELECT ds.id FROM data_source ds
            JOIN supplier s ON s.id = ds.supplier_id
            WHERE s.prefix = 'MIK');  -- замени префикс
"
```

После сброса — перезалить прайс в UI (REPLACE).

## Чистка всех данных одного поставщика

Удалить **все позиции прайса** конкретного поставщика, оставив самого
поставщика и его data_source (с настройками: prefix, transformations,
column_mapping). Полезно когда хочется начать импорт с чистого листа,
не пересоздавая поставщика.

Сначала найди ID:

```bash
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "
SELECT s.id, s.name, s.prefix, ds.id AS source_id,
  (SELECT count(*) FROM item WHERE source_id = ds.id) AS items
FROM supplier s
LEFT JOIN data_source ds ON ds.supplier_id = s.id
ORDER BY s.name;"
```

Удали все позиции этого источника (CASCADE удалит match_candidate;
verification.chosen_item_id обнулится):

```bash
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "
DELETE FROM item WHERE source_id = '<SOURCE_UUID>';"
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "VACUUM ANALYZE item;"
```

Опционально — сбросить кэш column_mapping чтобы следующий импорт
заново определил шапку:

```bash
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "
UPDATE data_source SET config = '{}'::jsonb, last_synced_at = NULL
WHERE id = '<SOURCE_UUID>';"
```

После этого поставщик в UI остаётся, его прайс — пустой. Можно сразу
залить новый файл.

## Удаление поставщика целиком

Полностью убрать поставщика вместе со всеми его данными — позициями,
маппингом, настройками, ссылками из истории матчей.

> **Каскад:** `supplier → data_source → item → match_candidate` — все
> удалятся автоматически (ON DELETE CASCADE). `verification.chosen_item_id`
> обнулится через SET NULL — старые верификации сохраняются, но указывают
> на «удалённую позицию».
>
> Восстановить из бэкапа можно только через restore-db (целиком).
> Если нужно сохранить историю — лучше **не удалять**, а оставить
> поставщика с пустым прайсом (раздел выше).

Найди ID:

```bash
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "
SELECT id, name, prefix FROM supplier ORDER BY created_at;"
```

**Перед удалением сделай бэкап:**

```bash
cd /home/master/fasttender && ./deploy/bootstrap.sh backup-db
```

Удали:

```bash
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "
DELETE FROM supplier WHERE id = '<SUPPLIER_UUID>';"
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "VACUUM ANALYZE item, data_source, supplier;"
```

Проверь:

```bash
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "
SELECT s.name, count(i.id) AS items
FROM supplier s
LEFT JOIN data_source ds ON ds.supplier_id = s.id
LEFT JOIN item i ON i.source_id = ds.id
GROUP BY s.id, s.name ORDER BY s.name;"
```

## Бэкап / восстановление БД

```bash
cd /home/master/fasttender
./deploy/bootstrap.sh backup-db                                 # → backups/fasttender_YYYYMMDD-HHMMSS.sql.gz
./deploy/bootstrap.sh restore-db backups/fasttender_*.sql.gz   # внимание: перезапишет текущую БД
```

Бэкапы хранятся в `./backups/`, размер ~10-20 MB сжатого.

## Backfill auto-link каталога

Если каталог был обновлён, а прайсы поставщиков не пере-загружались —
ссылки на каталог не пересчитаны. Запустить пере-расчёт по всем
прайс-источникам:

```bash
docker exec ft_prod_app uv run python -c "
import asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from fasttender.core.config import get_settings
from fasttender.models import DataSource, DataSourceType
from fasttender.services.importer._base import auto_link_to_catalog

async def go():
    eng = create_async_engine(str(get_settings().database_url))
    fac = async_sessionmaker(eng, expire_on_commit=False)
    async with fac() as s:
        # Снимаем все auto-ссылки (manual оставляем)
        await s.execute(text(
            \"UPDATE item SET linked_catalog_item_id = NULL, catalog_link_source = NULL \"
            \"WHERE catalog_link_source = 'auto'\"
        ))
        await s.commit()
        sources = (await s.scalars(
            select(DataSource).where(DataSource.type == DataSourceType.SUPPLIER_PRICELIST)
        )).all()
        for src in sources:
            linked = await auto_link_to_catalog(s, src.id)
            await s.commit()
            print(f'{src.name}: linked {linked}')
    await eng.dispose()

asyncio.run(go())
"
```

## Backfill supplier_sku

Срабатывает автоматически при PATCH /suppliers/{id} с новым prefix.
Если что-то пошло не так — можно запустить руками:

```bash
docker exec ft_prod_app uv run python -c "
import asyncio
from uuid import UUID
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from fasttender.core.config import get_settings
from fasttender.services.importer._base import backfill_supplier_skus

async def go():
    eng = create_async_engine(str(get_settings().database_url))
    fac = async_sessionmaker(eng, expire_on_commit=False)
    async with fac() as s:
        n = await backfill_supplier_skus(s, UUID('<SUPPLIER_UUID>'), '<PREFIX>')
        await s.commit()
        print(f'Backfilled: {n}')
    await eng.dispose()

asyncio.run(go())
"
```

## Применить новую миграцию на проде

```bash
cd /home/master/fasttender
./deploy/bootstrap.sh backup-db   # ВСЕГДА перед миграцией

# Билд образа миграций
docker compose -f docker-compose.prod.yml --env-file .env.prod build migrations

# Применить (нужен пароль postgres из .env.prod)
PG_PASS=$(grep '^POSTGRES_PASSWORD' .env.prod | cut -d= -f2)
docker run --rm --network fasttender_default \
  -e FT_DATABASE_URL_SYNC="postgresql+psycopg://fasttender:${PG_PASS}@postgres:5432/fasttender" \
  -e FT_DATABASE_URL="postgresql+asyncpg://fasttender:${PG_PASS}@postgres:5432/fasttender" \
  fasttender-migrations:latest uv run alembic upgrade head

# Проверить текущую версию
docker exec ft_prod_postgres psql -U fasttender -d fasttender -c "SELECT version_num FROM alembic_version;"
```

`docker compose run migrations` НЕ работает — оркестратор пытается
поднять зависимые сервисы и иногда задевает postgres-контейнер.
Используем `docker run` напрямую через сетку.

## Пересборка и перезапуск app+worker+frontend

```bash
cd /home/master/fasttender
docker compose -f docker-compose.prod.yml --env-file .env.prod build app worker frontend-build
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --force-recreate app worker caddy
docker logs ft_prod_app --tail 10   # smoke
```

## Откат деплоя

```bash
cd /home/master/fasttender
git checkout HEAD~1                            # или конкретный SHA
docker compose -f docker-compose.prod.yml --env-file .env.prod build app worker frontend-build
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --force-recreate app worker caddy
# Если миграция тоже откатывается — alembic downgrade -1 через docker run выше
```

## Просмотр логов

```bash
docker logs -f ft_prod_app          # бэкенд
docker logs -f ft_prod_worker       # celery
docker logs -f ft_prod_caddy        # https + basic auth
docker logs -f ft_prod_postgres     # DB
```

## Диагностика исчезновения контейнеров

См. `deploy/DIAGNOSTICS.md` — отдельный документ про инциденты
30 мая 2026.
