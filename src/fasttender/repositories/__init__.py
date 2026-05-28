"""Repositories: абстракции доступа к данным.

Главный участник Фазы 1 — SearchRepository (раздел 12.6 архитектуры).
"""

from fasttender.repositories.search import SearchHit, SearchRepository, SourceFilter

__all__ = [
    "SearchHit",
    "SearchRepository",
    "SourceFilter",
]
