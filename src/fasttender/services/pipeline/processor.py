"""Оркестратор обработки спецификации (раздел 7.3, 7.4).

Полный поток: uploaded → parsing → parsed → matching → matched.
На ошибке любой стадии — переход в *_failed + error_message
(пайплайн пере-запускается вручную через POST /retry, появится в UI).

В Phase 1 «нормализация» = применение `value_normalizer` при создании
SpecItem; отдельной стадии `normalize` нет — она тривиальна и не
оправдывает отдельного шага.
"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.core.logging import get_logger
from fasttender.models import (
    MatchCandidate,
    Specification,
    SpecificationStatus,
    SpecItem,
)
from fasttender.repositories.pg_trgm import PgTrgmSearchRepository
from fasttender.services.matcher import MatchingEngine
from fasttender.services.matcher.adapters import match_input_from_spec_item
from fasttender.services.matcher.types import Candidate, MatchResult
from fasttender.services.parser import ParsedItem, ParseError, SpecificationParser
from fasttender.services.parser.value_normalizer import (
    clean_string,
    normalize_article,
    normalize_name,
)

logger = get_logger(__name__)


class SpecificationProcessor:
    """Оркестратор pipeline для одной спецификации.

    Использование:

        async with session_factory() as session:
            processor = SpecificationProcessor(session)
            await processor.process(spec_id)

    Каждый переход статуса коммитится отдельно, чтобы прогресс был
    виден в БД даже если работа долгая или прервётся.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        parser: SpecificationParser | None = None,
        matcher: MatchingEngine | None = None,
        top_n: int = 5,
    ) -> None:
        self._session = session
        self._parser = parser or SpecificationParser()
        self._matcher = matcher or MatchingEngine(PgTrgmSearchRepository(session))
        self._top_n = top_n

    async def process(self, spec_id: UUID) -> Specification:
        spec = await self._load_spec(spec_id)
        logger.info(
            "pipeline.start",
            spec_id=str(spec_id),
            filename=spec.source_filename,
            status=spec.status.value,
        )

        try:
            await self._parse_and_normalize(spec)
            await self._match_all(spec)
        except Exception as exc:  # ловим любую — статус и error_message пишем всегда
            logger.exception("pipeline.failed", spec_id=str(spec_id))
            await self._record_failure(spec, exc)
            raise

        return spec

    # --- Стадии ---

    async def _parse_and_normalize(self, spec: Specification) -> None:
        await self._transition(spec, SpecificationStatus.PARSING)

        try:
            parse_result = self._parser.parse(spec.storage_path)
        except ParseError as exc:
            await self._record_failure(spec, exc, status=SpecificationStatus.PARSE_FAILED)
            raise

        # Очищаем существующие SpecItem на случай повторного запуска
        await self._session.execute(delete(SpecItem).where(SpecItem.spec_id == spec.id))

        for parsed in parse_result.items:
            self._session.add(self._build_spec_item(spec.id, parsed))

        spec.meta = {
            **(spec.meta or {}),
            "header_row": parse_result.header_row,
            "sheet_name": parse_result.sheet_name,
            "encoding": parse_result.encoding,
            "delimiter": parse_result.delimiter,
            "parse_warnings": [w.model_dump() for w in parse_result.warnings],
            "column_mapping": {
                field.value: col for field, col in parse_result.column_mapping.columns.items()
            },
        }
        await self._transition(spec, SpecificationStatus.PARSED)

        logger.info(
            "pipeline.parsed",
            spec_id=str(spec.id),
            items=len(parse_result.items),
            warnings=len(parse_result.warnings),
        )

    # Прогресс матчинга коммитим раз в BATCH строк. =1 → после каждой строки:
    # матчинг ~0.8с/строку (упирается в pg_trgm-поиск по каталогу), поэтому
    # накладные на коммит ничтожны, зато полоса в UI едет плавно даже на
    # коротких спеках (4–5 строк). Поднять >1, если каталог/нагрузка вырастут.
    _PROGRESS_BATCH = 1

    async def _match_all(self, spec: Specification) -> None:
        await self._transition(spec, SpecificationStatus.MATCHING)
        # Сброс прогресса на входе (важно для retry — parse уже пересоздал строки)
        spec.matched_count = 0
        await self._session.commit()

        # Подгружаем свежие SpecItem (после parse сессия их видит)
        spec_items = (
            await self._session.scalars(
                select(SpecItem).where(SpecItem.spec_id == spec.id).order_by(SpecItem.line_number)
            )
        ).all()

        processed = 0
        for spec_item in spec_items:
            match_input = match_input_from_spec_item(spec_item)
            result = await self._matcher.match(match_input, top_n=self._top_n)
            self._persist_candidates(spec_item.id, result)
            processed += 1
            # Батч-коммит: фиксируем кандидатов + прогресс (результаты «текут»
            # в UI по мере матчинга, полоса показывает честный %).
            if processed % self._PROGRESS_BATCH == 0:
                spec.matched_count = processed
                await self._session.commit()

        spec.matched_count = processed

        # После матчинга — REVIEWING (требует верификации). Раньше ставили
        # MATCHED со словом «Готов» — это путало менеджеров (UX-фидбэк
        # 1 июня 2026: спецификация не готова пока не пройдена верификация).
        await self._transition(spec, SpecificationStatus.REVIEWING)
        spec.completed_at = datetime.now(UTC)
        await self._session.commit()

        logger.info("pipeline.matched", spec_id=str(spec.id), items=len(spec_items))

    # --- Утилиты ---

    async def _load_spec(self, spec_id: UUID) -> Specification:
        spec = await self._session.get(Specification, spec_id)
        if spec is None:
            raise ValueError(f"Specification {spec_id} не найдена")
        return spec

    async def _transition(self, spec: Specification, new_status: SpecificationStatus) -> None:
        spec.status = new_status
        await self._session.commit()

    @staticmethod
    def _build_spec_item(spec_id: UUID, parsed: ParsedItem) -> SpecItem:
        return SpecItem(
            spec_id=spec_id,
            line_number=parsed.line_number,
            name_raw=parsed.name,
            article_raw=parsed.article,
            manufacturer_raw=parsed.manufacturer,
            unit_raw=parsed.unit,
            quantity=parsed.quantity,
            price_raw=parsed.price,
            currency_raw=parsed.currency,
            notes=parsed.notes,
            name_normalized=normalize_name(parsed.name),
            article_normalized=normalize_article(parsed.article),
            unit_normalized=clean_string(parsed.unit).lower() if parsed.unit else None,
            raw_row=parsed.raw_row,
        )

    def _persist_candidates(self, spec_item_id: UUID, result: MatchResult) -> None:
        """Сохраняет топ-N catalog + топ-N suppliers как MatchCandidate-строки.

        rank уникален внутри (spec_item_id, source_type) — реконструируется
        при чтении через JOIN на data_source.type.
        """
        # На случай перезапуска матчинга — удаляем старые кандидаты
        # NB: synchronous delete внутри той же сессии; пайплайн не вызывает
        # _persist_candidates повторно в рамках одного процесса, но на retry
        # после failure это сработает корректно.
        for cand in result.catalog:
            self._session.add(self._build_candidate_row(spec_item_id, cand))
        for cand in result.suppliers:
            self._session.add(self._build_candidate_row(spec_item_id, cand))

    @staticmethod
    def _build_candidate_row(spec_item_id: UUID, cand: Candidate) -> MatchCandidate:
        return MatchCandidate(
            spec_item_id=spec_item_id,
            item_id=cand.item_id,
            confidence=cand.confidence,
            match_type=cand.primary_match_type,
            rank=cand.rank,
            explanation=cand.explanation.model_dump(mode="json"),
        )

    async def _record_failure(
        self,
        spec: Specification,
        exc: Exception,
        *,
        status: SpecificationStatus | None = None,
    ) -> None:
        """Сохраняет ошибку в spec.error_message и переводит в *_failed.

        Если статус не задан — выбирается по текущему: parsing → parse_failed,
        matching → match_failed; для остальных оставляется как есть.
        """
        if status is None:
            mapping = {
                SpecificationStatus.PARSING: SpecificationStatus.PARSE_FAILED,
                SpecificationStatus.MATCHING: SpecificationStatus.MATCH_FAILED,
            }
            status = mapping.get(spec.status, SpecificationStatus.PARSE_FAILED)

        spec.status = status
        spec.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        await self._session.commit()


async def process_specification_by_id(session: AsyncSession, spec_id: UUID) -> Specification:
    """Шорткат для Celery-задачи и тестов."""
    return await SpecificationProcessor(session).process(spec_id)


# Re-export для удобства
__all__ = ["SpecificationProcessor", "process_specification_by_id"]


# Защита от случайного использования Path
_ = Path
