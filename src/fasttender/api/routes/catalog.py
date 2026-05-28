"""Каталог компании (раздел 4.3, Приложение C.4).

TODO Phase 1: импорт каталога, поиск по каталогу.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/search", summary="Поиск по каталогу (TODO Phase 1)")
async def search_catalog(q: str = "", limit: int = 20) -> dict[str, list]:
    return {"results": []}
