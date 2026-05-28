"""Поставщики и их прайсы (раздел 4.3, Приложение C.4).

TODO Phase 1: CRUD поставщиков, импорт прайсов по шаблону.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("/", summary="Список поставщиков (TODO Phase 1)")
async def list_suppliers() -> dict[str, list]:
    return {"items": []}
