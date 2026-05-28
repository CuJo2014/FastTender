"""Спецификации (раздел 4.1, Приложение C.4).

В Фазе 1 реализуется минимальный набор: загрузка, статус, позиции с кандидатами,
верификация, экспорт. Контракт — раздел Приложения C.4.

TODO Фаза 1: реализация после готовности парсера, нормализатора и матчера.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/specifications", tags=["specifications"])


@router.get("/", summary="Список спецификаций (TODO Phase 1)")
async def list_specifications() -> dict[str, list]:
    return {"items": []}
