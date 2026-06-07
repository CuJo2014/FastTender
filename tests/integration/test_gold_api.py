"""HTTP-тесты золотого датасета: CRUD, посев из строки спеки, экспорт→eval.

Round-trip экспорта — главный тест: подтверждает, что выгруженный из БД
Excel читается тем же `eval_gold.run_eval`, что и заполняемый вручную шаблон.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fasttender.main import create_app
from fasttender.models import (
    Item,
    Specification,
    SpecificationStatus,
    SpecItem,
    Verification,
    VerificationDecision,
)
from fasttender.scripts.eval_gold import run_eval
from fasttender.services.importer import CatalogImporter, ImportMode
from tests.fixtures.spec_builders import make_xlsx
from tests.integration.conftest import TEST_DB_URL

# gold_row первым: ссылается на spec_item/item (CASCADE подхватит и так).
_TABLES = (
    "gold_row",
    "verification",
    "match_candidate",
    "spec_item",
    "specification",
    "item",
    "data_source",
    "supplier",
)


@pytest_asyncio.fixture
async def committed_db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL, future=True)
    async with engine.connect() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
        await conn.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.connect() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
        await conn.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from fasttender.core import db as core_db

    await core_db.dispose_engine()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await core_db.dispose_engine()


async def _seed_catalog(session: AsyncSession, tmp_path: Path) -> Item:
    """Засевает каталог из одной позиции и возвращает её ORM-объект."""
    catalog = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Производитель", "Ед.", "Цена"],
            ["BLT-M10-040-ZN", "Болт М10х40 DIN 933 оцинкованный", "KOELNER", "шт", "12.50"],
        ],
    )
    await CatalogImporter().import_file(session, catalog, mode=ImportMode.REPLACE)
    await session.commit()
    item = (
        await session.scalars(select(Item).where(Item.article_raw == "BLT-M10-040-ZN"))
    ).one()
    return item


# --- CRUD ---


async def test_create_update_delete_gold_row(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    item = await _seed_catalog(committed_db, tmp_path)

    # Создание с эталоном через expected_item_id → снимок из каталога
    r = await client.post(
        "/api/v1/gold-rows/",
        json={
            "name": "Болт М10х40 оцинков.",
            "article": "BLT-M10-040-ZN",
            "manufacturer": "KOELNER",
            "quantity": 50,
            "unit": "шт",
            "expected_item_id": str(item.id),
            "label_status": "найдено",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    gold_id = body["id"]
    # Снимок эталона снят из позиции каталога
    assert body["expected_article"] == "BLT-M10-040-ZN"
    assert body["expected_name"] == "Болт М10х40 DIN 933 оцинкованный"
    assert body["expected_item_id"] == str(item.id)
    assert body["label_status"] == "найдено"

    # Список
    lst = await client.get("/api/v1/gold-rows/")
    assert lst.status_code == 200
    assert [g["id"] for g in lst.json()] == [gold_id]

    # Фильтр по статусу: «аналог» пустой
    empty = await client.get("/api/v1/gold-rows/", params={"label_status": "аналог"})
    assert empty.json() == []

    # Изменение статуса и примечания
    patched = await client.patch(
        f"/api/v1/gold-rows/{gold_id}",
        json={"label_status": "сомнительно", "labeler_notes": "перепроверить"},
    )
    assert patched.status_code == 200
    assert patched.json()["label_status"] == "сомнительно"
    assert patched.json()["labeler_notes"] == "перепроверить"

    # Удаление
    deleted = await client.delete(f"/api/v1/gold-rows/{gold_id}")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/gold-rows/")).json() == []


async def test_create_gold_row_explicit_expected_overrides_snapshot(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    item = await _seed_catalog(committed_db, tmp_path)
    r = await client.post(
        "/api/v1/gold-rows/",
        json={
            "name": "Болт",
            "expected_item_id": str(item.id),
            "expected_name": "Кастомное имя эталона",
            "label_status": "найдено",
        },
    )
    assert r.status_code == 201
    # Явное expected_name приоритетнее снимка, но код 1С/артикул из снимка
    assert r.json()["expected_name"] == "Кастомное имя эталона"
    assert r.json()["expected_article"] == "BLT-M10-040-ZN"


# --- Посев из строки спеки ---


async def test_from_spec_item_uses_chosen_item(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    item = await _seed_catalog(committed_db, tmp_path)

    spec = Specification(
        source_filename="spec1.xlsx",
        storage_path="/tmp/spec1.xlsx",
        status=SpecificationStatus.REVIEWING,
    )
    committed_db.add(spec)
    await committed_db.flush()
    spec_item = SpecItem(
        spec_id=spec.id,
        line_number=1,
        name_raw="Болт М10х40 у клиента",
        article_raw="м10*40",
        manufacturer_raw="без бренда",
        unit_raw="шт",
        quantity=50,
        raw_row={},
    )
    committed_db.add(spec_item)
    await committed_db.flush()
    committed_db.add(
        Verification(
            spec_item_id=spec_item.id,
            chosen_item_id=item.id,
            decision=VerificationDecision.CONFIRMED,
        )
    )
    await committed_db.commit()

    r = await client.post(
        "/api/v1/gold-rows/from-spec-item",
        json={"spec_item_id": str(spec_item.id)},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # Клиентские поля скопированы из строки спеки
    assert body["name"] == "Болт М10х40 у клиента"
    assert body["article"] == "м10*40"
    assert body["source_file"] == "spec1.xlsx"
    assert body["spec_item_id"] == str(spec_item.id)
    # Эталон взят из выбранной позиции; статус выведен как «найдено»
    assert body["expected_article"] == "BLT-M10-040-ZN"
    assert body["expected_item_id"] == str(item.id)
    assert body["label_status"] == "найдено"


async def test_from_spec_item_without_verification_is_not_found(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    spec = Specification(
        source_filename="spec2.xlsx",
        storage_path="/tmp/spec2.xlsx",
        status=SpecificationStatus.REVIEWING,
    )
    committed_db.add(spec)
    await committed_db.flush()
    spec_item = SpecItem(
        spec_id=spec.id,
        line_number=1,
        name_raw="Неведомая позиция",
        raw_row={},
    )
    committed_db.add(spec_item)
    await committed_db.commit()

    r = await client.post(
        "/api/v1/gold-rows/from-spec-item",
        json={"spec_item_id": str(spec_item.id)},
    )
    assert r.status_code == 201
    assert r.json()["label_status"] == "не найдено"
    assert r.json()["expected_item_id"] is None


async def test_from_spec_item_404_when_missing(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/gold-rows/from-spec-item",
        json={"spec_item_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 404


# --- Экспорт → eval round-trip ---


async def test_export_roundtrip_with_eval_gold(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    item = await _seed_catalog(committed_db, tmp_path)

    # Строка эталона: клиентский артикул совпадает с каталожным → матчер
    # обязан вернуть позицию на 1-м месте.
    r = await client.post(
        "/api/v1/gold-rows/",
        json={
            "name": "Болт М10х40 оцинков. DIN933",
            "article": "BLT-M10-040-ZN",
            "manufacturer": "KOELNER",
            "quantity": 50,
            "unit": "шт",
            "expected_item_id": str(item.id),
            "label_status": "найдено",
        },
    )
    assert r.status_code == 201

    # Выгрузка в Excel-шаблон
    exp = await client.get("/api/v1/gold-rows/export.xlsx")
    assert exp.status_code == 200
    assert "spreadsheetml" in exp.headers["content-type"]
    xlsx_path = tmp_path / "gold_export.xlsx"
    xlsx_path.write_bytes(exp.content)

    # Прогон eval по выгруженному файлу (CLI-путь, без изменений)
    out_path = tmp_path / "gold_result.xlsx"
    metrics = await run_eval(input_path=xlsx_path, output_path=out_path, top_k=5)

    assert metrics.applicable == 1
    assert metrics.recall_at_k_hits == 1
    assert metrics.precision_at_1_hits == 1
