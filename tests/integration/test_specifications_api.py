"""HTTP-флоу спецификаций (POST upload → GET status → GET items).

В отличие от других integration-тестов, тут нельзя использовать
savepoint-сессию: HTTP-эндпоинты ходят через свой engine, и savepoint-
commit невидим другим connection'ам. Поэтому используем committed_db
фикстуру с явным TRUNCATE в setup/teardown.
"""

import io
from collections.abc import AsyncIterator
from pathlib import Path

import openpyxl
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fasttender.core.celery_app import celery_app
from fasttender.core.config import get_settings
from fasttender.main import create_app
from fasttender.models import DataSource, DataSourceType, Item, SpecItem
from fasttender.services.importer import CatalogImporter, ImportMode
from tests.fixtures.spec_builders import make_xlsx
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


@pytest.fixture(autouse=True)
def _eager_celery():  # type: ignore[no-untyped-def]
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True


@pytest_asyncio.fixture
async def committed_db() -> AsyncIterator[AsyncSession]:
    """Реальная сессия с commit'ами; setup/teardown truncate'ит таблицы."""
    engine = create_async_engine(TEST_DB_URL, future=True)
    async with engine.connect() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
        await connection.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.connect() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
        await connection.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP-клиент против настоящего FastAPI-приложения."""
    from fasttender.core import db as core_db

    await core_db.dispose_engine()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await core_db.dispose_engine()


@pytest.fixture(autouse=True)
def _cleanup_uploads():  # type: ignore[no-untyped-def]
    yield
    settings = get_settings()
    if settings.upload_dir.exists():
        for f in settings.upload_dir.iterdir():
            try:
                f.unlink()
            except OSError:
                pass


def _make_spec_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Наименование", "Артикул", "Кол-во"])
    ws.append(["Болт М10х40", "BLT-M10-040", 50])
    ws.append(["Гайка М10", "NUT-M10", 100])
    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()


async def _seed_catalog(session: AsyncSession, tmp_path: Path) -> None:
    catalog = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["BLT-M10-040", "Болт М10х40 DIN933 оцинкованный", "12.50"],
            ["NUT-M10", "Гайка М10 DIN934", "4.20"],
        ],
    )
    await CatalogImporter().import_file(session, catalog, mode=ImportMode.REPLACE)
    await session.commit()


# --- POST /specifications/ ---


async def test_upload_returns_202_with_spec_id(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    await _seed_catalog(committed_db, tmp_path)

    response = await client.post(
        "/api/v1/specifications/",
        files={
            "file": (
                "spec.xlsx",
                _make_spec_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
        params={"client_name": "ООО Ромашка"},
    )
    assert response.status_code == 202
    body = response.json()
    assert "spec_id" in body
    assert body["filename"] == "spec.xlsx"


async def test_upload_with_client_id_links_client_and_name(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    await _seed_catalog(committed_db, tmp_path)
    created = await client.post("/api/v1/clients/", json={"name": "ООО Подшипник"})
    assert created.status_code == 201
    cid = created.json()["id"]

    resp = await client.post(
        "/api/v1/specifications/",
        files={
            "file": (
                "spec.xlsx",
                _make_spec_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
        params={"client_id": cid},
    )
    assert resp.status_code == 202
    spec_id = resp.json()["spec_id"]

    spec = (await client.get(f"/api/v1/specifications/{spec_id}")).json()
    assert spec["client_id"] == cid
    # client_name денормализуется из выбранного клиента
    assert spec["client_name"] == "ООО Подшипник"


async def test_upload_with_unknown_client_id_returns_404(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    resp = await client.post(
        "/api/v1/specifications/",
        files={
            "file": (
                "spec.xlsx",
                _make_spec_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
        params={"client_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404


async def test_upload_rejects_unsupported_extension(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    response = await client.post(
        "/api/v1/specifications/",
        files={"file": ("bad.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 415


# --- Полный HTTP-флоу ---


async def test_full_http_flow_upload_then_get_status_then_get_items(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    await _seed_catalog(committed_db, tmp_path)

    upload_resp = await client.post(
        "/api/v1/specifications/",
        files={
            "file": (
                "spec.xlsx",
                _make_spec_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    assert upload_resp.status_code == 202
    spec_id = upload_resp.json()["spec_id"]

    status_resp = await client.get(f"/api/v1/specifications/{spec_id}")
    assert status_resp.status_code == 200
    spec = status_resp.json()
    # После матчинга статус «reviewing» (UX-фидбэк 1 июня 2026)
    assert spec["status"] == "reviewing"
    assert spec["counts"]["items_total"] == 2
    assert spec["counts"]["items_matched_high"] == 2

    items_resp = await client.get(f"/api/v1/specifications/{spec_id}/items")
    assert items_resp.status_code == 200
    body = items_resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2

    blt = body["items"][0]
    assert blt["name_raw"] == "Болт М10х40"
    assert blt["article_normalized"] == "BLTM10040"
    assert len(blt["candidates_catalog"]) == 1
    top = blt["candidates_catalog"][0]
    assert top["confidence"] >= 0.95
    assert top["match_type"] == "exact_article"
    assert top["rank"] == 1
    assert "human_readable" in top["explanation"]


async def test_items_include_manually_chosen_item_not_in_candidates(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    """Менеджер выбрал позицию через поиск (нет среди топ-кандидатов) →
    в ответе verification.chosen_item = именно эта позиция, не топ-кандидат."""
    await _seed_catalog(committed_db, tmp_path)

    # Позиция, которой НЕТ среди кандидатов спеки
    cat_source = await committed_db.scalar(
        select(DataSource).where(DataSource.type == DataSourceType.COMPANY_CATALOG)
    )
    washer = Item(
        source_id=cat_source.id,
        article_raw="WSH-M10",
        article_normalized="WSHM10",
        name="Шайба М10 DIN125",
        is_active=True,
    )
    committed_db.add(washer)
    await committed_db.commit()
    await committed_db.refresh(washer)

    upload = await client.post(
        "/api/v1/specifications/",
        files={
            "file": (
                "spec.xlsx",
                _make_spec_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    spec_id = upload.json()["spec_id"]

    items = (await client.get(f"/api/v1/specifications/{spec_id}/items")).json()["items"]
    blt = next(i for i in items if i["name_raw"] == "Болт М10х40")
    # топ-кандидат — Болт, не Шайба
    assert blt["candidates_catalog"][0]["name"] != "Шайба М10 DIN125"

    # менеджер подтверждает Шайбой (через «поиск»)
    verify = await client.post(
        f"/api/v1/specifications/{spec_id}/items/{blt['id']}/verify",
        json={"decision": "confirmed", "chosen_item_id": str(washer.id)},
    )
    assert verify.status_code == 200

    items2 = (await client.get(f"/api/v1/specifications/{spec_id}/items")).json()["items"]
    blt2 = next(i for i in items2 if i["id"] == blt["id"])
    v = blt2["verification"]
    assert v["decision"] == "confirmed"
    assert v["chosen_item"] is not None
    assert v["chosen_item"]["item_id"] == str(washer.id)
    assert v["chosen_item"]["name"] == "Шайба М10 DIN125"
    assert v["chosen_item"]["source_type"] == "company_catalog"


async def test_delete_specification_removes_it_and_cascades(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    """DELETE спецификации: 204, сама спека и её строки/кандидаты/верификации
    удалены; позиции каталога (Item) НЕ затронуты."""
    await _seed_catalog(committed_db, tmp_path)
    catalog_before = await committed_db.scalar(select(func.count()).select_from(Item))

    upload = await client.post(
        "/api/v1/specifications/",
        files={
            "file": (
                "spec.xlsx",
                _make_spec_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    spec_id = upload.json()["spec_id"]

    # есть строки после матчинга
    items_before = (await client.get(f"/api/v1/specifications/{spec_id}/items")).json()
    assert items_before["total"] == 2

    resp = await client.delete(f"/api/v1/specifications/{spec_id}")
    assert resp.status_code == 204

    # спецификация исчезла
    assert (await client.get(f"/api/v1/specifications/{spec_id}")).status_code == 404
    # строки каскадно удалены
    remaining = await committed_db.scalar(
        select(func.count()).select_from(SpecItem).where(SpecItem.spec_id == spec_id)
    )
    assert remaining == 0
    # каталог не пострадал
    catalog_after = await committed_db.scalar(select(func.count()).select_from(Item))
    assert catalog_after == catalog_before


async def test_delete_specification_404_for_unknown_id(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    resp = await client.delete(
        "/api/v1/specifications/00000000-0000-0000-0000-000000000009"
    )
    assert resp.status_code == 404


async def test_patch_specification_requisites(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    """PATCH реквизитов тендера → сохраняются и возвращаются в GET."""
    from fasttender.models import Specification

    spec = Specification(source_filename="s.xlsx", storage_path="/tmp/s.xlsx")
    committed_db.add(spec)
    await committed_db.commit()
    await committed_db.refresh(spec)

    patched = await client.patch(
        f"/api/v1/specifications/{spec.id}",
        json={
            "spec_number": "44-ФЗ/2026-001",
            "spec_date": "2026-06-01",
            "delivery_date": "2026-07-15",
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["spec_number"] == "44-ФЗ/2026-001"
    assert body["spec_date"] == "2026-06-01"
    assert body["delivery_date"] == "2026-07-15"

    got = (await client.get(f"/api/v1/specifications/{spec.id}")).json()
    assert got["delivery_date"] == "2026-07-15"


async def test_get_specification_404_for_unknown_id(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    response = await client.get("/api/v1/specifications/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 404


async def test_list_specifications_returns_recent_first(
    client: AsyncClient,
    committed_db: AsyncSession,
    tmp_path: Path,
) -> None:
    await _seed_catalog(committed_db, tmp_path)

    spec_bytes = _make_spec_bytes()
    spec_ids = []
    for _ in range(3):
        resp = await client.post(
            "/api/v1/specifications/",
            files={
                "file": (
                    "spec.xlsx",
                    spec_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            },
        )
        spec_ids.append(resp.json()["spec_id"])

    list_resp = await client.get("/api/v1/specifications/")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 3
    ids_returned = [i["id"] for i in items]
    assert set(ids_returned) == set(spec_ids)
