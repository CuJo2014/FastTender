"""Сервис верификации (раздел 4.7, 9.5).

Verification — единственная запись на SpecItem (unique constraint в БД),
поэтому повторная верификация перезаписывает предыдущую. Это нормально:
менеджер может передумать.

В Phase 2 здесь же будет накопление обратной связи для re-ranker'а и
словарей синонимов (раздел 9.5), пока — просто фиксация решения.
"""

from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fasttender.core.logging import get_logger
from fasttender.models import (
    DataSourceType,
    Item,
    MatchCandidate,
    SpecItem,
    Verification,
)
from fasttender.models.enums import VerificationDecision

logger = get_logger(__name__)


class VerificationError(Exception):
    """Не удалось зафиксировать решение (битый chosen_item_id, отсутствующий SpecItem)."""


class VerificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        spec_id: UUID,
        spec_item_id: UUID,
        decision: VerificationDecision,
        chosen_item_id: UUID | None = None,
        notes: str | None = None,
        decided_by: str | None = None,
    ) -> Verification:
        """Создаёт или обновляет Verification для указанной строки.

        Проверяет, что SpecItem действительно принадлежит spec_id и что
        chosen_item_id (если задан) ссылается на существующую активную позицию.
        """
        spec_item = await self._load_spec_item(spec_id, spec_item_id)

        if chosen_item_id is not None:
            await self._ensure_chosen_item_exists(chosen_item_id)

        existing = await self._session.scalar(
            select(Verification).where(Verification.spec_item_id == spec_item.id)
        )

        if existing is None:
            existing = Verification(
                spec_item_id=spec_item.id,
                decision=decision,
                chosen_item_id=chosen_item_id,
                notes=notes,
                decided_by=decided_by,
            )
            self._session.add(existing)
        else:
            existing.decision = decision
            existing.chosen_item_id = chosen_item_id
            existing.notes = notes
            existing.decided_by = decided_by

        await self._session.flush()
        return existing

    async def delete(self, *, spec_id: UUID, spec_item_id: UUID) -> bool:
        """Удаляет Verification строки (откат к «не верифицировано»).

        Проверяет, что SpecItem принадлежит spec_id. Возвращает True, если
        запись была и удалена; False, если верификации не было.
        """
        spec_item = await self._load_spec_item(spec_id, spec_item_id)
        existing = await self._session.scalar(
            select(Verification).where(Verification.spec_item_id == spec_item.id)
        )
        if existing is None:
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

    async def auto_confirm(
        self,
        *,
        spec_id: UUID,
        min_confidence: float,
        decided_by: str | None = None,
        only_unverified: bool = True,
    ) -> tuple[int, int, int]:
        """Массово подтверждает строки с уверенностью ≥ min_confidence.

        Стратегия: для каждой строки спецификации берём топ-1 кандидата из
        каталога компании (приоритетнее, чем поставщик — раздел 4.5: каталог
        первичен), и если его confidence ≥ порога — создаём Verification
        с decision=CONFIRMED. Если в каталоге пусто, смотрим на топ supplier.

        Возвращает (confirmed_count, skipped_already_verified, skipped_below_threshold).
        """
        targets, skipped_existing, skipped_low = await self._select_auto_confirm_targets(
            spec_id=spec_id,
            min_confidence=min_confidence,
            only_unverified=only_unverified,
        )
        for spec_item_id, item_id in targets:
            self._session.add(
                Verification(
                    spec_item_id=spec_item_id,
                    decision=VerificationDecision.CONFIRMED,
                    chosen_item_id=item_id,
                    decided_by=decided_by,
                )
            )
        await self._session.flush()
        return len(targets), skipped_existing, skipped_low

    async def count_auto_confirm_targets(
        self,
        *,
        spec_id: UUID,
        min_confidence: float,
        only_unverified: bool = True,
    ) -> tuple[int, int, int]:
        """Dry-run: сколько строк затронуло бы авто-подтверждение (без записи).

        Возвращает тот же кортеж, что и auto_confirm, но ничего не меняет —
        для счётчика «Авто-подтвердить (N)» в UI.
        """
        targets, skipped_existing, skipped_low = await self._select_auto_confirm_targets(
            spec_id=spec_id,
            min_confidence=min_confidence,
            only_unverified=only_unverified,
        )
        return len(targets), skipped_existing, skipped_low

    async def bulk_verify(
        self,
        *,
        spec_id: UUID,
        spec_item_ids: Sequence[UUID],
        decision: VerificationDecision,
        decided_by: str | None = None,
    ) -> tuple[int, int]:
        """Массовое решение по явно выбранным строкам.

        Для CONFIRMED подтверждает топ-кандидата каждой строки (каталог
        приоритетнее прайсов); строки без кандидата пропускает. Для прочих
        решений (rejected/…) применяет ко всем выбранным.

        Возвращает (applied, skipped_no_candidate).
        """
        if not spec_item_ids:
            return 0, 0

        # Только строки, реально принадлежащие этой спеке (чужие/несуществующие
        # молча игнорируем — UI мог прислать устаревший выбор).
        valid_ids = set(
            (
                await self._session.scalars(
                    select(SpecItem.id).where(
                        SpecItem.id.in_(spec_item_ids), SpecItem.spec_id == spec_id
                    )
                )
            ).all()
        )

        best_per_item: dict[UUID, MatchCandidate] = {}
        if decision is VerificationDecision.CONFIRMED:
            best_per_item = await self._best_candidate_per_item(valid_ids)

        applied = 0
        skipped_no_candidate = 0
        for sid in spec_item_ids:
            if sid not in valid_ids:
                continue
            chosen_item_id: UUID | None = None
            if decision is VerificationDecision.CONFIRMED:
                best = best_per_item.get(sid)
                if best is None:
                    skipped_no_candidate += 1
                    continue
                chosen_item_id = best.item_id
            await self.upsert(
                spec_id=spec_id,
                spec_item_id=sid,
                decision=decision,
                chosen_item_id=chosen_item_id,
                decided_by=decided_by,
            )
            applied += 1
        return applied, skipped_no_candidate

    # --- Внутренние ---

    async def _best_candidate_per_item(
        self, spec_item_ids: Collection[UUID]
    ) -> dict[UUID, MatchCandidate]:
        """Топ-кандидат на строку (rank=1): каталог приоритетнее прайсов,
        внутри одного типа — по убыванию confidence."""
        if not spec_item_ids:
            return {}
        candidates = (
            await self._session.scalars(
                select(MatchCandidate)
                .where(
                    MatchCandidate.spec_item_id.in_(spec_item_ids),
                    MatchCandidate.rank == 1,
                )
                .options(selectinload(MatchCandidate.item).selectinload(Item.source))
            )
        ).all()

        best_per_item: dict[UUID, MatchCandidate] = {}
        for cand in candidates:
            current = best_per_item.get(cand.spec_item_id)
            cand_priority = (
                0 if cand.item.source.type is DataSourceType.COMPANY_CATALOG else 1
            )
            if current is None:
                best_per_item[cand.spec_item_id] = cand
                continue
            current_priority = (
                0 if current.item.source.type is DataSourceType.COMPANY_CATALOG else 1
            )
            if cand_priority < current_priority or (
                cand_priority == current_priority
                and cand.confidence > current.confidence
            ):
                best_per_item[cand.spec_item_id] = cand
        return best_per_item

    async def _select_auto_confirm_targets(
        self,
        *,
        spec_id: UUID,
        min_confidence: float,
        only_unverified: bool,
    ) -> tuple[list[tuple[UUID, UUID]], int, int]:
        """Строки под авто-подтверждение: (spec_item_id, chosen_item_id) +
        счётчики пропусков. Общая основа для apply (auto_confirm) и dry-run."""
        spec_item_ids = list(
            (
                await self._session.scalars(
                    select(SpecItem.id).where(SpecItem.spec_id == spec_id)
                )
            ).all()
        )
        if not spec_item_ids:
            return [], 0, 0

        already_verified: set[UUID] = set()
        if only_unverified:
            rows = await self._session.scalars(
                select(Verification.spec_item_id).where(
                    Verification.spec_item_id.in_(spec_item_ids)
                )
            )
            already_verified = set(rows.all())

        best_per_item = await self._best_candidate_per_item(spec_item_ids)

        targets: list[tuple[UUID, UUID]] = []
        skipped_existing = 0
        skipped_low = 0
        for spec_item_id in spec_item_ids:
            if spec_item_id in already_verified:
                skipped_existing += 1
                continue
            best = best_per_item.get(spec_item_id)
            if best is None or float(best.confidence) < min_confidence:
                skipped_low += 1
                continue
            targets.append((spec_item_id, best.item_id))
        return targets, skipped_existing, skipped_low

    async def _load_spec_item(self, spec_id: UUID, spec_item_id: UUID) -> SpecItem:
        spec_item = await self._session.get(SpecItem, spec_item_id)
        if spec_item is None:
            raise VerificationError(f"SpecItem {spec_item_id} не найден")
        if spec_item.spec_id != spec_id:
            raise VerificationError(
                f"SpecItem {spec_item_id} не относится к спецификации {spec_id}"
            )
        return spec_item

    async def _ensure_chosen_item_exists(self, item_id: UUID) -> None:
        item = await self._session.get(Item, item_id)
        if item is None:
            raise VerificationError(f"Item {item_id} не найден")
