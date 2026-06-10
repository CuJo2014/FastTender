"""GET /catalog/search — поиск по Коду 1С / Артикулу / Наименованию.

UX-фидбэк 1 июня 2026: менеджер должен иметь возможность найти
каталог-карточку напрямую (когда знает что нужен Ц0000001234) и
привязать её к строке спецификации без скроллинга кандидатов.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fasttender.main import create_app
from fasttender.services.importer import CatalogImporter, ImportMode
from tests.fixtures.spec_builders import make_xlsx
from tests.integration.conftest import TEST_DB_URL

_TABLES = (
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
    from fasttender.core import db as core_db

    await core_db.dispose_engine()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await core_db.dispose_engine()


async def _seed(committed_db: AsyncSession, tmp_path: Path) -> None:
    catalog = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Код", "Наименование", "Цена", "Производитель"],
            ["BLT-001", "Ц0000000100", "Болт М10х40 DIN933", "10", "Завод"],
            ["NUT-001", "Ц0000000200", "Гайка М10 DIN934", "4", "Метизы"],
            ["WSH-XYZ", None, "Шайба М10 особенная", "1", None],
        ],
    )
    await CatalogImporter().import_file(committed_db, catalog, mode=ImportMode.REPLACE)
    await committed_db.commit()


async def test_search_by_code_1c_exact(
    client: AsyncClient, committed_db: AsyncSession, tmp_path: Path
) -> None:
    await _seed(committed_db, tmp_path)
    resp = await client.get("/api/v1/catalog/search?q=Ц0000000100")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["code_1c"] == "Ц0000000100"
    assert data[0]["name"] == "Болт М10х40 DIN933"


async def test_search_by_article_normalized(
    client: AsyncClient, committed_db: AsyncSession, tmp_path: Path
) -> None:
    await _seed(committed_db, tmp_path)
    # Артикул в каталоге «BLT-001» нормализуется в «BLT001»
    resp = await client.get("/api/v1/catalog/search?q=blt-001")
    assert resp.status_code == 200
    data = resp.json()
    assert any(r["article"] == "BLT-001" for r in data)


async def test_search_by_name_substring(
    client: AsyncClient, committed_db: AsyncSession, tmp_path: Path
) -> None:
    await _seed(committed_db, tmp_path)
    resp = await client.get("/api/v1/catalog/search?q=особенная")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Шайба М10 особенная"


async def test_search_empty_query_returns_empty(
    client: AsyncClient, committed_db: AsyncSession, tmp_path: Path
) -> None:
    await _seed(committed_db, tmp_path)
    resp = await client.get("/api/v1/catalog/search?q=")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_no_catalog_returns_empty(client: AsyncClient) -> None:
    """Если каталог компании не загружен — поиск возвращает пустой список."""
    resp = await client.get("/api/v1/catalog/search?q=blah")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_includes_supplier_pricelist_by_sku(
    client: AsyncClient, committed_db: AsyncSession, tmp_path: Path
) -> None:
    """Поиск находит позиции и в прайсах поставщиков (по supplier_sku или артикулу)."""
    from fasttender.models import Supplier
    from fasttender.services.importer import PriceListImporter

    await _seed(committed_db, tmp_path)
    supplier = Supplier(name="ТестПоставщик", prefix="TST", contact_email=None, meta={})
    committed_db.add(supplier)
    await committed_db.flush()
    pl = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["UNIQUE-001", "Уникальный товар поставщика", "99"],
        ],
    )
    await PriceListImporter().import_file(
        committed_db, supplier_id=supplier.id, path=pl, mode=ImportMode.REPLACE
    )
    await committed_db.commit()

    # 1. По уникальному имени — должна найтись прайс-позиция
    resp = await client.get("/api/v1/catalog/search?q=Уникальный")
    assert resp.status_code == 200
    data = resp.json()
    assert any(r["source_type"] == "supplier_pricelist" for r in data)
    sup_result = next(r for r in data if r["source_type"] == "supplier_pricelist")
    assert sup_result["source_label"] == "Прайс: ТестПоставщик"
    assert sup_result["supplier_sku"] == "TST-000001"

    # 2. По supplier_sku точно
    resp = await client.get("/api/v1/catalog/search?q=TST-000001")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["supplier_sku"] == "TST-000001"

    # 3. С include_suppliers=false — прайсы не возвращаются
    resp = await client.get("/api/v1/catalog/search?q=Уникальный&include_suppliers=false")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_exact_matches_above_ilike(
    client: AsyncClient, committed_db: AsyncSession, tmp_path: Path
) -> None:
    """Точное совпадение по code_1c сортируется выше чем ILIKE по имени."""
    await _seed(committed_db, tmp_path)
    # «Болт» ILIKE найдёт «Болт М10х40», но если параллельно есть точный
    # code_1c — он должен быть первым
    resp = await client.get("/api/v1/catalog/search?q=Ц0000000200")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["code_1c"] == "Ц0000000200"


async def test_catalog_not_pushed_out_by_pricelists_for_name_query(
    client: AsyncClient, committed_db: AsyncSession, tmp_path: Path
) -> None:
    """Регрессия: прайсы (code_1c IS NULL) не должны вытеснять каталог из топ-N.

    Был баг сортировки: `(code_1c == q).desc()` ставил NULL первыми (NULLS
    FIRST) → прайсы всплывали выше каталога. Теперь COALESCE → каталог первым.
    """
    from fasttender.models import Supplier
    from fasttender.services.importer import PriceListImporter

    catalog = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Код", "Наименование", "Цена"],
            ["MOL-1", "Ц0000009999", "Молоток слесарный 500г", "100"],
        ],
    )
    await CatalogImporter().import_file(committed_db, catalog, mode=ImportMode.REPLACE)
    await committed_db.commit()

    supplier = Supplier(name="ООО Прайс", meta={})
    committed_db.add(supplier)
    await committed_db.flush()
    pricelist = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["P1", "Молоток A", "10"],
            ["P2", "Молоток B", "11"],
            ["P3", "Молоток C", "12"],
        ],
    )
    await PriceListImporter().import_file(
        committed_db, supplier_id=supplier.id, path=pricelist, mode=ImportMode.REPLACE
    )
    await committed_db.commit()

    # limit=2: при баге каталог вытеснялся бы тремя прайс-молотками
    r = await client.get("/api/v1/catalog/search", params={"q": "Молоток", "limit": 2})
    assert r.status_code == 200
    results = r.json()
    assert results, "ожидали результаты"
    # Каталог идёт первым и присутствует в выдаче
    assert results[0]["source_type"] == "company_catalog"
    assert any(x["source_type"] == "company_catalog" for x in results)
