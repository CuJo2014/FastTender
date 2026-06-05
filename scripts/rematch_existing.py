"""Аккуратный re-match существующих спецификаций под новый матчинг.

Для каждой строки каждой спеки: удаляет старые MatchCandidate, прогоняет
текущий MatchingEngine, записывает новые кандидаты. НЕ трогает Verification,
SpecItem (без ре-парсинга) и статус спеки. Печатает before/after, включая
счётчик верификаций (должен остаться неизменным).

Запуск внутри прод-контейнера app:
    docker cp scripts/rematch_existing.py ft_prod_app:/tmp/rematch.py
    docker exec ft_prod_app /app/.venv/bin/python /tmp/rematch.py
"""

import asyncio

from sqlalchemy import delete, func, select, text

from fasttender.core.db import get_session_factory
from fasttender.models import MatchCandidate, Specification, SpecItem, Verification
from fasttender.repositories.pg_trgm import PgTrgmSearchRepository
from fasttender.services.matcher import MatchingEngine
from fasttender.services.matcher.adapters import match_input_from_spec_item


async def _dist(session) -> str:  # type: ignore[no-untyped-def]
    row = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE confidence>=0.9) AS hi, "
                "count(*) FILTER (WHERE confidence>=0.5 AND confidence<0.9) AS mid, "
                "count(*) FILTER (WHERE confidence<0.5) AS lo, "
                "coalesce(max(confidence),0) AS mx "
                "FROM match_candidate WHERE rank=1"
            )
        )
    ).first()
    return f">=0.9: {row.hi} | 0.5-0.9: {row.mid} | <0.5: {row.lo} | max: {float(row.mx):.3f}"


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        verif_before = await session.scalar(select(func.count()).select_from(Verification))
        cand_before = await session.scalar(select(func.count()).select_from(MatchCandidate))
        print(f"BEFORE: верификаций={verif_before}, кандидатов={cand_before}")
        print(f"BEFORE распределение (rank=1): {await _dist(session)}")

        matcher = MatchingEngine(PgTrgmSearchRepository(session))
        specs = (await session.scalars(select(Specification))).all()
        total = 0
        for spec in specs:
            items = (
                await session.scalars(
                    select(SpecItem).where(SpecItem.spec_id == spec.id)
                )
            ).all()
            for si in items:
                # Удаляем старых кандидатов этой строки (Core delete — выполняется
                # сразу в транзакции, до вставки новых → нет конфликта по rank).
                await session.execute(
                    delete(MatchCandidate).where(MatchCandidate.spec_item_id == si.id)
                )
                result = await matcher.match(match_input_from_spec_item(si), top_n=5)
                for cand in (*result.catalog, *result.suppliers):
                    session.add(
                        MatchCandidate(
                            spec_item_id=si.id,
                            item_id=cand.item_id,
                            confidence=cand.confidence,
                            match_type=cand.primary_match_type,
                            rank=cand.rank,
                            explanation=cand.explanation.model_dump(mode="json"),
                        )
                    )
                total += 1
            await session.flush()
            print(f"  спека {spec.source_filename}: {len(items)} строк пере-матчено")

        await session.commit()

        verif_after = await session.scalar(select(func.count()).select_from(Verification))
        cand_after = await session.scalar(select(func.count()).select_from(MatchCandidate))
        print(f"\nAFTER: верификаций={verif_after}, кандидатов={cand_after}, строк={total}")
        print(f"AFTER распределение (rank=1): {await _dist(session)}")
        assert verif_before == verif_after, "ВЕРИФИКАЦИИ ИЗМЕНИЛИСЬ — что-то не так!"
        print("OK: верификации сохранены (before == after).")


asyncio.run(main())
