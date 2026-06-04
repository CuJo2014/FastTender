"""HTTP-тесты справочника торговых площадок + флаг ТП на спеке."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fasttender.main import create_app
from fasttender.models import Specification
from tests.integration.conftest import TEST_DB_URL

_TABLES = (
    "verification",
    "match_candidate",
    "spec_item",
    "specification",
    "client",
    "trading_platform",
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


async def test_crud_platform(client: AsyncClient, committed_db: AsyncSession) -> None:
    r = await client.post(
        "/api/v1/trading-platforms/",
        json={"name": "Сбербанк-АСТ", "url": "https://sberbank-ast.ru"},
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    dup = await client.post("/api/v1/trading-platforms/", json={"name": "Сбербанк-АСТ"})
    assert dup.status_code == 409

    found = await client.get("/api/v1/trading-platforms/", params={"q": "сбер"})
    assert [p["id"] for p in found.json()] == [pid]

    assert (await client.delete(f"/api/v1/trading-platforms/{pid}")).status_code == 204
    assert (await client.get(f"/api/v1/trading-platforms/{pid}")).status_code == 404


async def test_is_tp_flag_and_platform_assignment(
    client: AsyncClient, committed_db: AsyncSession
) -> None:
    spec = Specification(source_filename="s.xlsx", storage_path="/tmp/s.xlsx")
    committed_db.add(spec)
    await committed_db.commit()
    await committed_db.refresh(spec)

    pid = (
        await client.post("/api/v1/trading-platforms/", json={"name": "РТС-тендер"})
    ).json()["id"]

    # выбор площадки → is_tp=true + денорм имя
    r = await client.patch(
        f"/api/v1/specifications/{spec.id}", json={"trading_platform_id": pid}
    )
    assert r.status_code == 200
    assert r.json()["trading_platform_id"] == pid
    assert r.json()["is_tp"] is True
    assert r.json()["trading_platform"] == "РТС-тендер"

    # площадка показывает счётчик
    got = await client.get(f"/api/v1/trading-platforms/{pid}")
    assert got.json()["specifications_count"] == 1

    # снятие флага is_tp=false → очистка площадки
    off = await client.patch(
        f"/api/v1/specifications/{spec.id}", json={"is_tp": False}
    )
    assert off.json()["is_tp"] is False
    assert off.json()["trading_platform_id"] is None
    assert off.json()["trading_platform"] is None

    # несуществующая площадка → 422
    bad = await client.patch(
        f"/api/v1/specifications/{spec.id}",
        json={"trading_platform_id": "00000000-0000-0000-0000-000000000009"},
    )
    assert bad.status_code == 422
