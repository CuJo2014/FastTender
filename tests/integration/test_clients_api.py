"""HTTP-тесты справочника клиентов + привязка спеки к клиенту."""

from collections.abc import AsyncIterator

import pytest
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


async def test_create_list_search_client(client: AsyncClient, committed_db: AsyncSession) -> None:
    r = await client.post("/api/v1/clients/", json={"name": "ООО Ромашка", "inn": "7701234567"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["specifications_count"] == 0

    # дубликат имени → 409
    dup = await client.post("/api/v1/clients/", json={"name": "ООО Ромашка"})
    assert dup.status_code == 409

    await client.post("/api/v1/clients/", json={"name": "ЗАО Бета"})

    # список
    all_resp = await client.get("/api/v1/clients/")
    assert {c["name"] for c in all_resp.json()} == {"ООО Ромашка", "ЗАО Бета"}
    # поиск
    found = await client.get("/api/v1/clients/", params={"q": "ромаш"})
    assert [c["id"] for c in found.json()] == [cid]


async def test_update_and_delete_client(client: AsyncClient, committed_db: AsyncSession) -> None:
    cid = (await client.post("/api/v1/clients/", json={"name": "Старое имя"})).json()["id"]

    patched = await client.patch(f"/api/v1/clients/{cid}", json={"name": "Новое имя", "inn": "123"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Новое имя"
    assert patched.json()["inn"] == "123"

    assert (await client.delete(f"/api/v1/clients/{cid}")).status_code == 204
    assert (await client.get(f"/api/v1/clients/{cid}")).status_code == 404


async def test_assign_client_to_specification(
    client: AsyncClient, committed_db: AsyncSession
) -> None:
    """PATCH спеки client_id → привязка + денормализация client_name."""
    spec = Specification(source_filename="s.xlsx", storage_path="/tmp/s.xlsx")
    committed_db.add(spec)
    await committed_db.commit()
    await committed_db.refresh(spec)

    cid = (await client.post("/api/v1/clients/", json={"name": "ООО Альфа"})).json()["id"]

    patched = await client.patch(
        f"/api/v1/specifications/{spec.id}", json={"client_id": cid}
    )
    assert patched.status_code == 200
    assert patched.json()["client_id"] == cid
    assert patched.json()["client_name"] == "ООО Альфа"  # денормализовано

    # клиент теперь показывает счётчик спек
    got = await client.get(f"/api/v1/clients/{cid}")
    assert got.json()["specifications_count"] == 1

    # отвязка: client_id=null
    unset = await client.patch(
        f"/api/v1/specifications/{spec.id}", json={"client_id": None}
    )
    assert unset.json()["client_id"] is None

    # несуществующий клиент → 422
    bad = await client.patch(
        f"/api/v1/specifications/{spec.id}",
        json={"client_id": "00000000-0000-0000-0000-000000000009"},
    )
    assert bad.status_code == 422


@pytest.mark.parametrize("payload", [{"name": ""}, {}])
async def test_create_client_validation(
    client: AsyncClient, committed_db: AsyncSession, payload: dict
) -> None:
    r = await client.post("/api/v1/clients/", json=payload)
    assert r.status_code == 422
