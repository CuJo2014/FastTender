# Design: ручной маппинг колонок / выбор строки шапки при загрузке

**Статус:** черновик для оценки и обсуждения с заказчиком.
**Дата:** 2026-06-03.
**Контекст:** встречаются прайсы без строки заголовков (данные сразу с
первой строки) или с нестандартной структурой. Сейчас такие файлы
готовят вручную в Excel (см. `deploy/OPERATIONS.md` → «Нестандартные
прайсы»). Вопрос: дать пользователю в UI указать строку «шапки» и/или
назначить колонки перед загрузкой прайса/спецификации.

---

## 1. Что уже есть в коде (фундамент готов ~60%)

Парсер уже поддерживает оба механизма — они просто не выведены в UI/API:

| Хук | Где | Назначение |
|---|---|---|
| `mapping_override: ColumnMapping` | `parse_excel` / `parse_csv` / `build_result` | явный маппинг «поле → индекс колонки», минует автодетект |
| `header_row_override: int` | там же | явно задаёт индекс строки шапки |
| `PriceListImporter.import_file(...)` | принимает **оба** параметра | — |
| `ColumnMapping` / `SpecField` | `schemas`/`types` (есть и на фронте `types/api.ts`) | `{article:0, name:1, price:2, …}` |

**Чего не хватает:**
- HTTP-эндпоинты загрузки не пробрасывают эти параметры:
  - прайс: `POST /suppliers/{id}/pricelists/import` — только `file`, `mode`, `sheet_name`;
  - спека: `POST /specifications/` — только `file`, `client_name`.
- Нет эндпоинта **preview** (показать первые N строк, чтобы пользователь выбрал строку/колонки).
- Нет UI.

---

## 2. Рекомендуемый UX: «Превью + маппинг»

Один поток покрывает и «указать строку шапки», и «назначить колонки»:

```
1. Пользователь выбирает файл
2. Бэкенд возвращает первые ~20 строк как сетку (grid)
3. Пользователь кликом отмечает СТРОКУ ШАПКИ
   (или ставит галку «без шапки — данные с первой строки»)
4. Система авто-предлагает маппинг (detect_header по выбранной строке)
5. Пользователь правит выпадашками над каждой колонкой:
   [Артикул ▾] [Наименование ▾] [Цена ▾] [— игнор —] …
6. «Загрузить» → импорт с mapping_override + header_row_override
```

Преимущество: пользователь видит реальные данные и не гадает про индексы.
«Безголовый» прайс = галка «без шапки» + назначить колонки.

---

## 3. Бэкенд

### A. Preview-эндпоинт (общий для прайса и спеки)
```
POST /parsing/preview   (multipart: file, sheet_name?)
→ {
    sheet_names: [...],
    rows: [[c0, c1, ...], ...до 20],
    suggested: { header_row: int|null, mapping: {field: col_idx} }
  }
```
- Читает файл во временный путь, materialize первых ~20 строк — логика уже
  есть в `excel.py/_materialize_worksheet` (разворачивает merged-ячейки).
- Прогоняет `detect_header` для авто-подсказки.
- **Оценка: ~0.5 дня.**

### B. Прайс (синхронный — проще)
- Добавить в `import_pricelist` параметры `header_row: int|None` и
  `mapping: JSON|None`, собрать `ColumnMapping`, пробросить в готовый
  `import_file(..., mapping_override=, header_row_override=)`.
- Ручной маппинг сохранять в `source.config` (logic `_save_mapping_to_config`
  уже есть) — переживёт ре-импорт.
- **Оценка: ~0.5 дня.**

### C. Спецификация (асинхронная — больше плумбинга)
- Парсинг идёт в Celery: `SpecificationProcessor._parse_and_normalize` зовёт
  `self._parser.parse(spec.storage_path)` без override.
- Нужно:
  1. при загрузке сохранить override в **`Specification.meta`** (JSONB-поле
     уже есть);
  2. процессор читает `spec.meta` и передаёт
     `mapping_override` / `header_row_override` в `parse()`.
- **Оценка: ~0.5–1 день.**

---

## 4. Фронтенд

- Компонент **`FilePreviewGrid`**: таблица первых строк; клик по строке =
  шапка; выпадашки `SpecField` над каждой колонкой; галка «без шапки».
- Встроить в `ImportPanel` (прайсы) и `SpecificationUploadPage` (спеки).
- `lib/api.ts`: `previewFile()` + параметры маппинга в
  `importPricelist` / `uploadSpecification`.
- Типы `ColumnMapping` / `SpecField` уже есть в `types/api.ts`.
- **Оценка: ~1 день** (грид + интеграция в обе точки).

---

## 5. Объём и фазирование

| Вариант | Объём | Что закрывает |
|---|---|---|
| **MVP** — только прайсы (синхрон) + preview + маппинг-модалка | **~1.5–2 дня** | 80% боли: нестандартные прайсы без Excel-правок |
| **Полный** — + спецификации (meta + процессор + upload-UI) | **+1–1.5 дня** | спеки тоже |

**Рекомендация:** начать с **MVP для прайсов** — там больше разнобоя
форматов и поток синхронный (проще). Спеки — вторым этапом по спросу
(у клиентов спеки чаще единичные → подготовить в Excel дешевле).

---

## 6. Риски / нюансы

- **Preview merged-ячеек:** `_materialize_worksheet` уже разворачивает
  merge — сетка покажет «как видит парсер» (WYSIWYG, это плюс).
- **Сохранение шаблона:** ручной маппинг прайса писать в `source.config`,
  как и автодетектированный — на будущие ре-импорты.
- **CSV кодировки/разделители:** preview использует тот же автодетект
  (`parse_csv` умеет chardet + sniff), либо дать выбор в UI.
- **Ценовые колонки net/gross:** ручной маппинг задаёт ОДНУ PRICE-колонку;
  мульти-цена (`detect_price_columns`) остаётся на автодетекте. Если нужно
  выбирать несколько ценовых вручную — отдельный шаг поверх этого.
- **Валидация:** обязателен хотя бы `name`; при «без шапки» извлечение
  начинается с первой строки (header_row = -1 / отдельный флаг).

---

## 7. Связанные места в коде

- Парсер: `src/fasttender/services/parser/{__init__,_matrix,excel,csv,header_detector}.py`
- Прайс-импорт: `src/fasttender/services/importer/pricelist.py`,
  эндпоинт `src/fasttender/api/routes/suppliers.py::import_pricelist`
- Спека: `src/fasttender/services/pipeline/processor.py`,
  эндпоинт `src/fasttender/api/routes/specifications.py::upload_specification`
- Модели: `Specification.meta` (JSONB), `DataSource.config` (JSONB)
- Фронт: `frontend/src/components/ImportPanel.tsx`,
  `frontend/src/pages/SpecificationUploadPage.tsx`, `frontend/src/lib/api.ts`
