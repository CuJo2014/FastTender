"""Интеграционные тесты verify + auto-confirm."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import (
    Item,
    Specification,
    SpecificationStatus,
    SpecItem,
    Verification,
)
from fasttender.models.enums import VerificationDecision
from fasttender.services.importer import CatalogImporter, ImportMode
from fasttender.services.pipeline import SpecificationProcessor
from fasttender.services.verification import VerificationError, VerificationService
from tests.fixtures.spec_builders import make_xlsx


@pytest.fixture
def service(session: AsyncSession) -> VerificationService:
    return VerificationService(session)


async def _setup_processed_spec(session: AsyncSession, tmp_path: Path) -> Specification:
    """Каталог + 3 строки спецификации: 2 в каталоге, 1 unknown."""
    catalog = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["BLT-001", "Болт М10х40", "10.00"],
            ["NUT-001", "Гайка М10", "4.00"],
        ],
    )
    await CatalogImporter().import_file(session, catalog, mode=ImportMode.REPLACE)
    await session.commit()

    spec_file = make_xlsx(
        tmp_path / "spec.xlsx",
        rows=[
            ["Наименование", "Артикул", "Кол-во"],
            ["Болт М10х40", "BLT-001", 50],
            ["Гайка М10", "NUT-001", 100],
            ["Непонятное", "ZZZ-NOPE", 1],
        ],
    )
    spec = Specification(
        source_filename="spec.xlsx",
        storage_path=str(spec_file),
        status=SpecificationStatus.UPLOADED,
        meta={},
    )
    session.add(spec)
    await session.commit()
    await session.refresh(spec)

    await SpecificationProcessor(session).process(spec.id)
    return spec


# --- POST verify ---


async def test_verify_confirmed_creates_record(
    session: AsyncSession,
    service: VerificationService,
    tmp_path: Path,
) -> None:
    spec = await _setup_processed_spec(session, tmp_path)
    spec_items = (await session.scalars(select(SpecItem).where(SpecItem.spec_id == spec.id))).all()
    blt = next(s for s in spec_items if s.article_normalized == "BLT001")

    catalog_item = await session.scalar(select(Item).where(Item.article_normalized == "BLT001"))
    assert catalog_item is not None

    verification = await service.upsert(
        spec_id=spec.id,
        spec_item_id=blt.id,
        decision=VerificationDecision.CONFIRMED,
        chosen_item_id=catalog_item.id,
        notes="OK",
        decided_by="manager-1",
    )
    await session.commit()

    assert verification.decision is VerificationDecision.CONFIRMED
    assert verification.chosen_item_id == catalog_item.id
    assert verification.notes == "OK"
    assert verification.decided_by == "manager-1"


async def test_verify_not_found_clears_chosen_item(
    session: AsyncSession,
    service: VerificationService,
    tmp_path: Path,
) -> None:
    spec = await _setup_processed_spec(session, tmp_path)
    unknown = await session.scalar(
        select(SpecItem).where(
            SpecItem.spec_id == spec.id, SpecItem.article_normalized == "ZZZNOPE"
        )
    )
    assert unknown is not None

    verification = await service.upsert(
        spec_id=spec.id,
        spec_item_id=unknown.id,
        decision=VerificationDecision.NOT_FOUND,
        chosen_item_id=None,
        notes="Уточнить у клиента",
    )
    await session.commit()
    assert verification.decision is VerificationDecision.NOT_FOUND
    assert verification.chosen_item_id is None


async def test_reverify_overwrites_previous(
    session: AsyncSession,
    service: VerificationService,
    tmp_path: Path,
) -> None:
    spec = await _setup_processed_spec(session, tmp_path)
    blt = await session.scalar(
        select(SpecItem).where(SpecItem.spec_id == spec.id, SpecItem.article_normalized == "BLT001")
    )
    catalog_item = await session.scalar(select(Item).where(Item.article_normalized == "BLT001"))

    # Первое решение — confirmed
    await service.upsert(
        spec_id=spec.id,
        spec_item_id=blt.id,
        decision=VerificationDecision.CONFIRMED,
        chosen_item_id=catalog_item.id,
    )
    await session.commit()

    # Переход на rejected
    v2 = await service.upsert(
        spec_id=spec.id,
        spec_item_id=blt.id,
        decision=VerificationDecision.REJECTED,
        notes="Передумал",
    )
    await session.commit()

    assert v2.decision is VerificationDecision.REJECTED
    assert v2.chosen_item_id is None

    # В БД должна остаться одна запись
    count = await session.scalar(select(Verification).where(Verification.spec_item_id == blt.id))
    assert count is not None


async def test_verify_wrong_spec_id_raises(
    session: AsyncSession,
    service: VerificationService,
    tmp_path: Path,
) -> None:
    spec = await _setup_processed_spec(session, tmp_path)
    blt = await session.scalar(select(SpecItem).where(SpecItem.spec_id == spec.id))
    with pytest.raises(VerificationError, match="не относится"):
        await service.upsert(
            spec_id=uuid4(),
            spec_item_id=blt.id,
            decision=VerificationDecision.REJECTED,
        )


async def test_verify_nonexistent_chosen_item_raises(
    session: AsyncSession,
    service: VerificationService,
    tmp_path: Path,
) -> None:
    spec = await _setup_processed_spec(session, tmp_path)
    blt = await session.scalar(select(SpecItem).where(SpecItem.spec_id == spec.id))
    with pytest.raises(VerificationError, match=r"Item.*не найден"):
        await service.upsert(
            spec_id=spec.id,
            spec_item_id=blt.id,
            decision=VerificationDecision.CONFIRMED,
            chosen_item_id=uuid4(),
        )


# --- Auto-confirm ---


async def test_auto_confirm_creates_verifications_for_high_confidence(
    session: AsyncSession,
    service: VerificationService,
    tmp_path: Path,
) -> None:
    spec = await _setup_processed_spec(session, tmp_path)

    confirmed, skipped_existing, skipped_low = await service.auto_confirm(
        spec_id=spec.id,
        min_confidence=0.9,
        decided_by="auto",
    )
    await session.commit()

    # 2 точных артикула должны автоподтвердиться (BLT-001, NUT-001)
    assert confirmed == 2
    assert skipped_existing == 0
    # ZZZ-NOPE — нет hit'ов или < 0.5
    assert skipped_low == 1

    verifications = (
        await session.scalars(
            select(Verification).join(SpecItem).where(SpecItem.spec_id == spec.id)
        )
    ).all()
    assert len(verifications) == 2
    for v in verifications:
        assert v.decision is VerificationDecision.CONFIRMED
        assert v.decided_by == "auto"
        assert v.chosen_item_id is not None


async def test_auto_confirm_respects_only_unverified(
    session: AsyncSession,
    service: VerificationService,
    tmp_path: Path,
) -> None:
    spec = await _setup_processed_spec(session, tmp_path)
    blt = await session.scalar(
        select(SpecItem).where(SpecItem.spec_id == spec.id, SpecItem.article_normalized == "BLT001")
    )

    # Менеджер вручную отметил «не найдено» (даже хотя матчер уверенно нашёл)
    await service.upsert(
        spec_id=spec.id,
        spec_item_id=blt.id,
        decision=VerificationDecision.REJECTED,
    )
    await session.commit()

    # Авто-подтверждение НЕ должно перезаписать ручное решение
    confirmed, skipped_existing, _ = await service.auto_confirm(
        spec_id=spec.id, min_confidence=0.9, only_unverified=True
    )
    await session.commit()

    assert skipped_existing == 1  # blt
    assert confirmed == 1  # только NUT-001

    blt_verif = await session.scalar(
        select(Verification).where(Verification.spec_item_id == blt.id)
    )
    assert blt_verif.decision is VerificationDecision.REJECTED


async def test_auto_confirm_uses_high_threshold_not_low(
    session: AsyncSession,
    service: VerificationService,
    tmp_path: Path,
) -> None:
    spec = await _setup_processed_spec(session, tmp_path)

    confirmed, _, skipped_low = await service.auto_confirm(spec_id=spec.id, min_confidence=0.99)
    # При очень высоком пороге exact-article (≈ 0.95) не пройдёт
    assert confirmed == 0
    assert skipped_low == 3
