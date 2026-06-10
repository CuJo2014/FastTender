"""HTTP-тесты: preview трансформаций (P3.7) и экспорт/импорт настроек (P3.8)."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fasttender.main import create_app
from tests.integration.conftest import TEST_DB_URL

_TABLES = ("item", "data_source", "supplier")


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


# --- P3.7 preview ---


async def test_preview_transform_brand_and_vat(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/suppliers/preview-transform",
        json={
            "transformations": {
                "brand_regex": r"^(.+?)\s*//\s*(.+?)$",
                "vat_included": True,
                "vat_rate": 20,
            },
            "name": "Болт М10 // Sparta",
            "price": "120",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Болт М10"
    assert body["manufacturer"] == "Sparta"
    assert float(body["price"]) == 100.0  # 120 / 1.2


async def test_preview_transform_defaults(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/suppliers/preview-transform",
        json={
            "transformations": {"default_unit": "шт", "default_currency": "RUB"},
            "name": "Гайка",
        },
    )
    assert r.status_code == 200
    assert r.json()["unit"] == "шт"
    assert r.json()["currency"] == "RUB"


# --- P3.8 export/import ---


async def test_export_import_settings(client: AsyncClient, committed_db: AsyncSession) -> None:
    await client.post(
        "/api/v1/suppliers/",
        json={"name": "Поставщик А", "transformations": {"default_unit": "шт"}},
    )
    await client.post("/api/v1/suppliers/", json={"name": "Поставщик Б"})

    exp = await client.get("/api/v1/suppliers/settings/export")
    assert exp.status_code == 200
    settings = exp.json()
    assert {s["name"] for s in settings} == {"Поставщик А", "Поставщик Б"}

    # Импорт: меняем настройки А, добавляем неизвестного
    imp = await client.post(
        "/api/v1/suppliers/settings/import",
        json=[
            {"name": "Поставщик А", "prefix": "AAA", "transformations": {"default_currency": "USD"}},
            {"name": "Неизвестный", "prefix": "ZZZ"},
        ],
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["applied"] == 1
    assert imp.json()["skipped_unknown"] == ["Неизвестный"]

    # Проверяем, что А обновился
    exp2 = (await client.get("/api/v1/suppliers/settings/export")).json()
    a = next(s for s in exp2 if s["name"] == "Поставщик А")
    assert a["prefix"] == "AAA"
    assert a["transformations"]["default_currency"] == "USD"
