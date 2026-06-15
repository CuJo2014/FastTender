# Интеграция FastTender → Uptrade API

**Дата:** 15 июня 2026
**Адресат:** команда разработки FastTender
**Назначение:** как FastTender обращается к API поставщика Uptrade (заказы, заявки
на закупку/RFQ) — авторизация по статическому ключу `X-API-Key`.

> Полная справка по API (все эндпоинты, фильтры, ленты `/new`) — в репозитории
> Uptrade: `Docs/API_ACCESS.md`. Здесь — только то, что нужно потребителю.

---

## 1. Базовый URL и учётка

- **Base URL:** `https://uptrade.arsenalpro.tech` (HTTPS, публично).
- **Потребитель:** учётка `ft_uptrade` в Uptrade (`api_users`), заведена под FastTender.
- **Авторизация:** заголовок **`X-API-Key: <ключ>`** в каждом запросе.
  Логин/JWT не нужен — ключ статический, без экспирации.

## 2. Где хранить ключ

⚠️ **Ключ — секрет, в репозиторий не коммитим.** Кладём в `.env` FastTender
(он в `.gitignore`):

```dotenv
# .env (FastTender)
UPTRADE_API_BASE=https://uptrade.arsenalpro.tech
UPTRADE_API_KEY=utk_…   # выдан владельцем Uptrade, см. секрет-хранилище
```

Сам ключ передаётся вне репозитория (получен при выпуске, показывается один раз).
Если ключ скомпрометирован — владелец Uptrade перевыпускает
(`POST /api-users/{id}/key`), прежний сразу инвалидируется.

## 3. Примеры запросов

```bash
# из окружения
BASE="$UPTRADE_API_BASE"; KEY="$UPTRADE_API_KEY"

# список заказов
curl -s -H "X-API-Key: $KEY" "$BASE/orders?limit=5"

# заявки, по которым можно подать предложение
curl -s -H "X-API-Key: $KEY" "$BASE/purchase-requests?can_offer=true&limit=20"
```

Python (httpx) — как это будет в коде FastTender:

```python
import os, httpx

BASE = os.environ["UPTRADE_API_BASE"]
HEADERS = {"X-API-Key": os.environ["UPTRADE_API_KEY"]}

async def fetch_new_purchase_requests() -> list[dict]:
    async with httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=30) as c:
        r = await c.get("/purchase-requests/new")  # лента новых, см. §4
        r.raise_for_status()
        return r.json()["results"]
```

## 4. Лента «новых» с авто-курсором (рекомендуется для синка)

`GET /orders/new` и `GET /purchase-requests/new` отдают записи, **появившиеся
после прошлого вызова**, и сами двигают серверный курсор. Курсор привязан к
учётке ключа (`ft_uptrade`) автоматически — у FastTender свой изолированный
поток, не конфликтует с другими потребителями.

```bash
# забрать новые заявки и сдвинуть курсор
curl -s -H "X-API-Key: $KEY" "$BASE/purchase-requests/new?limit=100"
# → {"count":N,"consumer":"ft_uptrade","advanced":true,"results":[...]}
```

- `peek=true` — посмотреть, не сдвигая курсор.
- `channel=<имя>` — отдельная независимая лента (если у FastTender несколько
  независимых потребителей одного ключа); курсор будет `ft_uptrade:<channel>`.
- `POST /…/new/reset` — сбросить курсор (следующий вызов отдаст всё с начала).

⚠️ При **первом** вызове курсор пустой → вернётся весь текущий бэклог постранично
(по `limit`, максимум 500 за раз) — добирать повторными вызовами, пока `count` > 0.

## 5. Основные эндпоинты (кратко)

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/orders` | список заказов (фильтры `status_id`, `seen_after`, `created_after`) |
| GET | `/orders/new` | лента новых заказов (авто-курсор) |
| GET | `/orders/{id}` | заказ + позиции (`items`) |
| GET | `/purchase-requests` | список заявок (фильтры `status_id`, `can_offer`, `seen_after`) |
| GET | `/purchase-requests/new` | лента новых заявок (авто-курсор) |
| GET | `/purchase-requests/{id}` | заявка + позиции + наши офферы (`?with_offers=true`) |

## 6. Ошибки

- `401` — нет/неверный/отозванный `X-API-Key` (или истёкший JWT, если используется он).
- `404` — ресурс не найден.
- `409` — синк уже идёт (для управляющих эндпоинтов Uptrade — FastTender их обычно не вызывает).
