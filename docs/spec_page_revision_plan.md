# План реализации ревизии страницы «Спецификация»

Источник требований: [`FastTender_revizia_interfeysa.html`](./FastTender_revizia_interfeysa.html)
Страница: `/specifications/:id` — `frontend/src/pages/SpecificationDetailPage.tsx` + `frontend/src/components/SpecItemRow.tsx`.

Документ разбивает 13 рекомендаций ревизии на **6 независимо выкатываемых PR**. Каждый PR самодостаточен, проходит ревью и деплоится отдельно по штатной процедуре (пересборка `frontend-build` + при необходимости `app`/`worker`).

> **Миграций БД не требуется ни в одном PR.** Счётчики считаются на лету (`_compute_counts`), фильтры — query-time, решения менеджера уже хранятся в `verification`. Это сильно снижает риск каждой выкатки.

---

## 0. Design lock — единая модель статуса строки (согласовать ДО PR3–PR6)

В мокапе строка имеет один `status ∈ {pending, confirmed, rejected, nomatch}`. В реальной модели это **две ортогональные оси**, и их нельзя складывать в одно поле:

| Ось | Источник | Значения |
|-----|----------|----------|
| **А. Решение менеджера** (workflow) | `verification.decision` (нет записи = `pending`) | `pending` / `confirmed` / `rejected` / `not_found` / `new_item_requested` |
| **Б. Качество сопоставления** (derived) | топ-1 кандидат (`rank=1`), его `confidence` и сам факт наличия | `high ≥0.9` / `mid 0.5–0.9` / `low <0.5` / `none` (кандидатов нет) |

`«Нет кандидата»` — это **ось Б = none**, а не решение. Строка может быть `none` И `confirmed` одновременно (менеджер нашёл через поиск).

**Решения, которые надо зафиксировать (предлагаемые значения по умолчанию):**

1. **UI-словарь оси А:** Не проверено · Подтверждено · Отклонено · Не найдено · Новая позиция. (Мокап сворачивает до 3 — но `not_found`/`new_item_requested` пишутся в экспорт, поэтому их нельзя терять в данных; визуально можно группировать, в данных — раздельно.)
2. **Значения сегментного фильтра** (один query-параметр `status`): `all` · `pending` · `confirmed` · `rejected` · `no_candidate`. Здесь `no_candidate` — единственное значение оси Б в фильтре; остальные — ось А. Семантика `no_candidate`: **кандидатов нет, независимо от решения** (чистая ось Б).
3. **Бакеты качества** берём из настроек: `high = settings.confidence_auto_confirm` (0.9), `min = settings.confidence_min` (0.5) — те же, что уже использует `_compute_counts`.

Этот раздел — не PR, а согласование. Без него PR4 (фильтры) и PR3 (метрики) придётся переделывать.

---

## PR 1 — Косметика и быстрые победы (frontend-only)

**Закрывает:** C1 (цвет уверенности vs решение), C3 (кол-во `18.0000`), E2 (деструктивное «Отказаться»), E3 (единый словарь статусов), E5 (размер страницы 100). Плюс проверка E1 (sticky).

**Зачем первым:** максимум ценности при нуле бэкенда и нуле риска; разблокирует визуальную часть остального.

**Изменения:**
- `lib/format.ts` — новый `formatQuantity(value)` (trim незначащих нулей: `18.0000 → 18`, `147.4900 → 147.49`; `toLocaleString("ru-RU", { maximumFractionDigits: 4 })` уже так умеет — вынести из `formatPrice` в общий хелпер).
- `components/ConfidenceCell.tsx` — проп `muted?: boolean`; при `true` рендерить нейтральный бейдж (`tone="neutral"` + рамка), не красить тоном. В `SpecItemRow` передавать `muted={!!item.verification}` (решение принято → score приглушён).
- `components/SpecItemRow.tsx` — колонка «Кол-во» через `formatQuantity`; бейдж решения — единый словарь (`renderVerificationBadge` уже близок, выровнять формулировки).
- `pages/SpecificationDetailPage.tsx` — `CancelButton` убрать в overflow-меню «⋯» (новый маленький компонент `OverflowMenu`) с подтверждением; дефолт `useState(pageSize = 100)`.
- E1: убедиться, что прод собран с текущим динамическим sticky (`top: stickyHeaderHeight + 56`) — в коде хардкода `283px` уже нет; вероятно пункт закрыт, только проверить на проде.

**API:** нет. **Тесты:** обновить/добавить юнит на `formatQuantity` (если есть фронт-тесты; иначе ручная проверка). **Риск:** низкий. **Объём:** S.

---

## PR 2 — Корректные счётчики: развести «< 50%» и «Нет кандидата» (backend + frontend)

**Закрывает:** C2 в части корректности данных (без редизайна сводки — он в PR3).

**Изменения:**
- `schemas/specification.py` → `SpecificationCounts`: добавить `items_low: int = 0` (кандидат есть, `confidence < min`) и `items_no_candidate: int = 0` (кандидатов нет совсем). `items_not_found` **оставить** как `items_low + items_no_candidate` (его потребляет список спек `GET /` — не ломаем).
- `api/routes/specifications.py` → `_compute_counts`: уже считает `low`; добавить `no_candidate = items_total - len(matched_ids)`; вернуть оба новых поля. (`matched_ids` = строки с топ-1 кандидатом.)
- `frontend/src/types/api.ts` → `SpecificationCounts`: добавить два поля.
- `frontend/src/pages/SpecificationDetailPage.tsx` → блок `Counter`'ов: показать «< 50%» (`items_low`) и «Нет кандидата» (`items_no_candidate`) раздельно. Проверка схождения: `high + medium + low + no_candidate = items_total`.

**API:** аддитивное расширение `SpecificationCounts` (обратносовместимо). **Тесты:** интеграционный на `_compute_counts` (строка без кандидата, строка с low, строка с high) — на standalone-PG. **Риск:** низкий. **Объём:** S–M.

---

## PR 3 — Двух-осевая сводка-метрик (frontend, зависит от PR2)

**Закрывает:** C2 полностью + E4 (компактная сводка).

**Изменения:**
- Новый компонент `components/SpecMetrics.tsx`: две оси из мокапа сводки —
  - **Прогресс верификации**: `items_verified / items_total`, прогресс-бар, «Закрыто / Осталось» (= `items_pending`).
  - **Качество сопоставления**: пропорциональная полоса `high/mid/low/none` (flex = количество) + легенда-чипы с числами.
- **Легенда = фильтр**: клик по чипу прокидывает выбранную категорию в состояние таблицы (общий параметр статуса — стыкуется с PR4). До мерджа PR4 чип может просто подсвечивать сегмент без фактической фильтрации (graceful).
- Встроить вместо текущего ряда из 5 `Counter` в шапке `SpecificationDetailPage`; компактная двухрядная компоновка.

**API:** нет (данные из PR2). **Тесты:** визуальная проверка + сходимость чисел. **Риск:** низкий (изолированный компонент). **Объём:** M.

---

## PR 4 — Серверные фильтр и сортировка строк (backend + frontend)

**Закрывает:** I1 (фильтр/сортировка). Зависит от Design lock.

**Почему бэкенд:** пагинация серверная (`GET /items?page&page_size`); клиентский фильтр затронет только текущую страницу из 100, а не все 823.

**Изменения:**
- `api/routes/specifications.py` → `get_specification_items`: добавить query-параметры
  - `status: str | None` — значения из Design lock (`pending`/`confirmed`/`rejected`/`not_found`/`new_item_requested`/`no_candidate`);
  - `sort: str = "line_number"` — `line_number` / `confidence_desc` / `confidence_asc`.
  - Фильтр оси А → `outerjoin(Verification)` + условие на `decision`/`IS NULL`.
  - Фильтр `no_candidate` → `NOT EXISTS (MatchCandidate где spec_item_id = …)`.
  - Сортировка по уверенности → подзапрос `max(confidence) where rank=1` на строку, `order_by` по нему (nulls last).
  - **`total` пересчитывать по отфильтрованному набору** (иначе пагинация врёт).
- `frontend/src/lib/api.ts` → `getSpecificationItems(specId, page, pageSize, { status?, sort? })`.
- `frontend/src/pages/SpecificationDetailPage.tsx`: сегменты статуса + дропдаун сортировки; `status`/`sort` входят в `queryKey`; смена фильтра/сортировки сбрасывает `page=1`.

**API:** аддитивные query-параметры (старые вызовы работают). **Тесты:** интеграционные — каждый фильтр и сортировка, корректность `total`. **Риск:** средний (сложность запроса, edge-кейсы с nulls). **Объём:** L.

---

## PR 5 — Инлайн-действия ✓ / ✗ в колонке «Решение» (frontend)

**Закрывает:** I2 (основное действие спрятано в ghost-кнопку «Кандидаты»).

**Изменения:**
- `components/SpecItemRow.tsx` — в колонке «Решение» для `pending`-строк: иконки ✓ (подтвердить топ-кандидата) / ✗ (отклонить) + ссылка «Кандидаты» (разворот, как сейчас). Для `confirmed`/`rejected` — статус + «↩ вернуть в работу» (уже есть `onUnverify`). Для `no_candidate` — ссылка «Подобрать» (открывает разворот с поиском).
- ✓ берёт `chosen_item_id` = топ-кандидат (`candidates_catalog[0] ?? candidates_suppliers[0]`) и шлёт существующий `verify(decision="confirmed", chosen_item_id)`. Без кандидата ✓ недоступна (вместо неё «Подобрать»).

**API:** нет — переиспользуем `POST /verify` и `DELETE /verify`. **Тесты:** ручная проверка состояний строки. **Риск:** низкий. **Объём:** M.

---

## PR 6 — Массовые операции + «Авто-подтвердить (N)» (backend + frontend)

**Закрывает:** I3 (bulk), I4 (счётчик авто-подтверждения).

**Изменения:**
- **Bulk-эндпоинт** `POST /{spec_id}/items/bulk-verify` `{ item_ids: UUID[], decision }`:
  - `confirmed` → подтверждает топ-кандидата каждой строки (строки без кандидата пропускает, возвращает их число);
  - `rejected` → ставит решение всем;
  - переиспользует `VerificationService.upsert` в цикле + один `_auto_promote_to_verified`. Возвращает `{ applied, skipped_no_candidate }`.
- **Счётчик авто-подтверждения**: `AutoConfirmRequest.dry_run: bool = False` → при `true` эндпоинт `auto-confirm` только считает целевые строки (`pending && top-conf ≥ min_confidence`) и возвращает число, ничего не меняя.
- `frontend/src/lib/api.ts`: `bulkVerify(...)`, `autoConfirmPreview(specId, minConfidence)`.
- `frontend/src/pages/SpecificationDetailPage.tsx` + `SpecItemRow.tsx`: чекбоксы строк + «выбрать все видимые» + bulk-бар (Подтвердить / Отклонить / Снять). Кнопка «Авто-подтвердить **(N)**»: дебаунс инпута «Порог» → `autoConfirmPreview` → показывает N, дизейбл при N=0.

**API:** новый bulk-эндпоинт + `dry_run` (аддитивно). **Тесты:** интеграционные на bulk-verify (включая пропуск no_candidate) и на `dry_run`-подсчёт. **Риск:** средний. **Объём:** L.

---

## Сводная таблица

| PR | Заголовок | Слой | Закрывает | Зависит | Объём | Риск |
|----|-----------|------|-----------|---------|-------|------|
| 1 | Косметика и быстрые победы | FE | C1, C3, E2, E3, E5 | — | S | низкий |
| 2 | Корректные счётчики (split «Не найдено») | BE+FE | C2 (данные) | — | S–M | низкий |
| 3 | Двух-осевая сводка-метрик | FE | C2, E4 | PR2 | M | низкий |
| 4 | Серверные фильтр и сортировка | BE+FE | I1 | Design lock | L | средний |
| 5 | Инлайн ✓/✗ в «Решение» | FE | I2 | — | M | низкий |
| 6 | Массовые операции + Авто-подтвердить (N) | BE+FE | I3, I4 | PR5 | L | средний |

**Рекомендуемый порядок:** Design lock → PR1 → PR2 → PR3 → (PR5 ∥ PR4) → PR6.
PR1, PR2, PR5 независимы и могут идти параллельно/в любом порядке. PR3 ждёт PR2; PR6 ждёт PR5.

**Тестовая БД:** интеграционные тесты гонять на одноразовом standalone-Postgres (`docker run`, свой порт, `alembic upgrade head`, удалить после) — **не** поднимать dev-compose (коллизия имени проекта `fasttender` с продом).
