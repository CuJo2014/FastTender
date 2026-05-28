# FastTender

Система автоматической обработки закупочных спецификаций.
Принимает Excel/CSV спецификации, сопоставляет позиции с каталогом компании
и прайсами поставщиков, выдаёт топ-N кандидатов с уверенностью.

Полный план — `docs/architecture_document.md`. Текущая стадия: **Фаза 1 (прототип)**.

## Стек (Фаза 1)

- Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic
- PostgreSQL 16 с `pg_trgm` + `tsvector`
- Celery 5 + Redis 7
- Парсинг: openpyxl, pandas, chardet
- Матчинг: rapidfuzz + PostgreSQL FTS
- Менеджер пакетов: [uv](https://docs.astral.sh/uv/)

## Быстрый старт

```bash
# 1. Поднять всё одной командой
docker compose up --build

# В отдельных терминалах будет доступно:
#   API:        http://localhost:8000/docs
#   Postgres:   localhost:5432  (user/pass: fasttender/fasttender, db: fasttender)
#   Redis:      localhost:6379
```

Миграции применяются автоматически сервисом `migrations` перед стартом `app` и `worker`.

### Проверка работоспособности

```bash
curl http://localhost:8000/health        # liveness
curl http://localhost:8000/health/ready  # readiness: проверяет БД и Redis
```

## Разработка локально (без Docker)

Требуется uv, PostgreSQL 16 (с pg_trgm) и Redis 7 локально.

```bash
# Установка uv (если ещё нет)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Установка зависимостей
uv sync --extra dev

# Применение миграций
uv run alembic upgrade head

# Запуск API
uv run uvicorn fasttender.main:app --reload

# Запуск воркера
uv run celery -A fasttender.core.celery_app:celery_app worker --loglevel=info
```

Переменные окружения — см. `.env.example` (префикс `FT_`).

## Тесты и линтеры

```bash
uv run pytest                          # все тесты
uv run pytest -m "not integration"     # только smoke (без БД)
uv run ruff check src tests            # линтер
uv run ruff format src tests           # автоформат
```

## Миграции

```bash
# Создать новую миграцию (вручную, не autogenerate — для контроля pg_trgm/tsvector)
uv run alembic revision -m "название миграции"

# Применить
uv run alembic upgrade head

# Откатить на один шаг
uv run alembic downgrade -1
```

## Структура

```
src/fasttender/
├── api/routes/         # HTTP-эндпоинты (раздел 4 архитектурного документа)
├── core/               # config, db, logging, celery
├── models/             # SQLAlchemy ORM (раздел 8.1)
├── schemas/            # Pydantic DTO
├── services/           # бизнес-логика, каждый сервис за интерфейсом (раздел 7.1)
│   ├── parser/         # XLSX/CSV → SpecItem (раздел 4.1, 10)
│   ├── normalizer/     # нормализация (раздел 4.2, 10.3)
│   ├── matcher/        # ядро (раздел 9)
│   └── importer/       # импорт каталога и прайсов (раздел 4.3)
├── repositories/       # SearchRepository и др. (раздел 12.6)
└── tasks/              # Celery задачи (раздел 7.3)

alembic/versions/       # миграции БД
tests/                  # pytest
docs/                   # архитектурный документ
```

## Дорожная карта

| Фаза | Срок | Содержание | Критерий перехода |
|---|---|---|---|
| 0 | заказчик, 3-4 нед | Сбор данных, чистка каталога, золотой датасет | Готовность данных |
| 1 | 4-6 нед | **Прототип — мы здесь** | Recall@5 на золотом датасете |
| 2 | ~4 мес | MVP: OpenSearch, vectors, LLM, OCR, веб-парсинг, 1С | Полный приём по разделу 17.3 |

См. `docs/architecture_document.md` разделы 15-17.
