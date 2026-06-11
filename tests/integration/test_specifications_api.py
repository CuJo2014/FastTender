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
from fasttender.models import (
    DataSource,
    DataSourceType,
    Item,
    MatchCandidate,
    MatchType,
    Specification,
    SpecificationStatus,
    SpecItem,
)
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


# --- Решение «Передать» (в группу МОС, миграция 0018) ---


async def test_forward_decision_counts_and_filter(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    """decision=forwarded фиксируется, считается отдельно (items_forwarded) и
    как верифицированная строка; фильтр status=forwarded её отдаёт."""
    spec, items = await _make_spec_with_items(committed_db, 3)

    # «Передать» — без выбранной позиции (как rejected/not_found)
    r = await client.post(
        f"/api/v1/specifications/{spec.id}/items/{items[1].id}/verify",
        json={"decision": "forwarded"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "forwarded"

    counts = (await client.get(f"/api/v1/specifications/{spec.id}")).json()["counts"]
    assert counts["items_forwarded"] == 1
    assert counts["items_verified"] == 1  # forwarded — это решение
    assert counts["items_pending"] == 2

    body = (
        await client.get(f"/api/v1/specifications/{spec.id}/items?status=forwarded")
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["line_number"] == 2
    assert body["items"][0]["verification"]["decision"] == "forwarded"


# --- Фильтр по качеству сопоставления (ось Б) ---


async def test_items_quality_filter_buckets_match_counts(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    """status=high/mid/low/no_candidate отдаёт ровно те строки, что считают
    счётчики сводки (_compute_counts): по топ-1 кандидату, пороги 0.9/0.5."""
    source = DataSource(type=DataSourceType.COMPANY_CATALOG, name="Каталог")
    committed_db.add(source)
    await committed_db.flush()

    # 3 позиции каталога под high/mid/low; 4-я строка — без кандидата
    items = [
        Item(source_id=source.id, name=f"Поз {i}", is_active=True) for i in range(3)
    ]
    committed_db.add_all(items)
    await committed_db.flush()

    spec = Specification(
        source_filename="q.xlsx",
        storage_path="/tmp/q.xlsx",
        status=SpecificationStatus.REVIEWING,
    )
    committed_db.add(spec)
    await committed_db.flush()
    rows = [
        SpecItem(spec_id=spec.id, line_number=n, name_raw=f"Строка {n}", raw_row={})
        for n in range(1, 5)
    ]
    committed_db.add_all(rows)
    await committed_db.flush()

    # топ-1 кандидаты: high=0.95, mid=0.70, low=0.30; 4-я строка без кандидата
    confidences = [0.95, 0.70, 0.30]
    committed_db.add_all(
        [
            MatchCandidate(
                spec_item_id=rows[i].id,
                item_id=items[i].id,
                confidence=confidences[i],
                match_type=MatchType.LEXICAL,
                rank=1,
                explanation={},
            )
            for i in range(3)
        ]
    )
    await committed_db.commit()

    base = f"/api/v1/specifications/{spec.id}/items"

    async def _lines(status: str) -> list[int]:
        body = (await client.get(f"{base}?status={status}")).json()
        return sorted(i["line_number"] for i in body["items"]), body["total"]

    high_lines, high_total = await _lines("high")
    assert high_lines == [1] and high_total == 1
    mid_lines, mid_total = await _lines("mid")
    assert mid_lines == [2] and mid_total == 1
    low_lines, low_total = await _lines("low")
    assert low_lines == [3] and low_total == 1
    nc_lines, nc_total = await _lines("no_candidate")
    assert nc_lines == [4] and nc_total == 1
    all_lines, all_total = await _lines("all")
    assert all_lines == [1, 2, 3, 4] and all_total == 4

    # числа на чипах сводки совпадают с фильтром
    spec_body = (await client.get(f"/api/v1/specifications/{spec.id}")).json()
    counts = spec_body["counts"]
    assert counts["items_matched_high"] == 1
    assert counts["items_matched_medium"] == 1
    assert counts["items_low"] == 1
    assert counts["items_no_candidate"] == 1


# --- Закладка строки (миграция 0017) ---


async def _make_spec_with_items(
    session: AsyncSession, n: int
) -> tuple[Specification, list[SpecItem]]:
    spec = Specification(source_filename="b.xlsx", storage_path="/tmp/b.xlsx")
    session.add(spec)
    await session.flush()
    items = [
        SpecItem(spec_id=spec.id, line_number=i, name_raw=f"Строка {i}", raw_row={})
        for i in range(1, n + 1)
    ]
    session.add_all(items)
    await session.commit()
    for it in items:
        await session.refresh(it)
    await session.refresh(spec)
    return spec, items


async def test_bookmark_set_move_and_clear_with_position(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    """PATCH ставит/переносит/снимает закладку; bookmarked_position = ранг по №."""
    spec, items = await _make_spec_with_items(committed_db, 3)
    base = f"/api/v1/specifications/{spec.id}"

    # ставим на 2-ю строку → позиция 2
    r = await client.patch(base, json={"bookmarked_item_id": str(items[1].id)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bookmarked_item_id"] == str(items[1].id)
    assert body["bookmarked_position"] == 2

    # GET тоже отдаёт закладку и позицию
    got = (await client.get(base)).json()
    assert got["bookmarked_item_id"] == str(items[1].id)
    assert got["bookmarked_position"] == 2

    # переносим на 3-ю → позиция 3 (одна закладка на спеку)
    r2 = await client.patch(base, json={"bookmarked_item_id": str(items[2].id)})
    assert r2.json()["bookmarked_position"] == 3

    # снимаем (null) → обоих полей нет
    r3 = await client.patch(base, json={"bookmarked_item_id": None})
    assert r3.json()["bookmarked_item_id"] is None
    assert r3.json()["bookmarked_position"] is None


async def test_bookmark_rejects_item_from_other_spec(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    """Закладка на строку из ЧУЖОЙ спеки → 422, ничего не меняется."""
    spec_a, _ = await _make_spec_with_items(committed_db, 2)
    _spec_b, items_b = await _make_spec_with_items(committed_db, 2)

    r = await client.patch(
        f"/api/v1/specifications/{spec_a.id}",
        json={"bookmarked_item_id": str(items_b[0].id)},
    )
    assert r.status_code == 422
    got = (await client.get(f"/api/v1/specifications/{spec_a.id}")).json()
    assert got["bookmarked_item_id"] is None


async def test_bookmark_cleared_when_item_deleted(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    """ON DELETE SET NULL: удаление отмеченной строки снимает закладку."""
    spec, items = await _make_spec_with_items(committed_db, 2)
    base = f"/api/v1/specifications/{spec.id}"

    await client.patch(base, json={"bookmarked_item_id": str(items[0].id)})
    assert (await client.get(base)).json()["bookmarked_item_id"] == str(items[0].id)

    # удаляем отмеченную строку напрямую
    await committed_db.delete(items[0])
    await committed_db.commit()

    got = (await client.get(base)).json()
    assert got["bookmarked_item_id"] is None
    assert got["bookmarked_position"] is None


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


# --- POST /specifications/{id}/abort ---


async def test_abort_in_progress_marks_cancelled(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    spec = Specification(
        source_filename="m.xlsx",
        storage_path="/tmp/m.xlsx",
        status=SpecificationStatus.MATCHING,
        meta={},
    )
    committed_db.add(spec)
    await committed_db.commit()

    r = await client.post(f"/api/v1/specifications/{spec.id}/abort")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cancelled"
    assert "прервана" in (body["error_message"] or "").lower()


async def test_abort_terminal_spec_409(
    client: AsyncClient,
    committed_db: AsyncSession,
) -> None:
    spec = Specification(
        source_filename="r.xlsx",
        storage_path="/tmp/r.xlsx",
        status=SpecificationStatus.REVIEWING,
        meta={},
    )
    committed_db.add(spec)
    await committed_db.commit()

    r = await client.post(f"/api/v1/specifications/{spec.id}/abort")
    assert r.status_code == 409


async def test_abort_unknown_404(client: AsyncClient, committed_db: AsyncSession) -> None:
    r = await client.post(
        "/api/v1/specifications/00000000-0000-0000-0000-000000000000/abort"
    )
    assert r.status_code == 404
