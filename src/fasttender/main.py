"""Точка входа FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fasttender import __version__
from fasttender.api.routes import (
    catalog,
    clients,
    gold,
    health,
    items,
    specifications,
    suppliers,
    trading_platforms,
)
from fasttender.core.config import get_settings
from fasttender.core.db import dispose_engine
from fasttender.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info("startup", version=__version__)
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="FastTender API",
        version=__version__,
        description="Обработка закупочных спецификаций — Фаза 1 (прототип)",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_prefix = "/api/v1"
    app.include_router(health.router)
    app.include_router(specifications.router, prefix=api_prefix)
    app.include_router(catalog.router, prefix=api_prefix)
    app.include_router(suppliers.router, prefix=api_prefix)
    app.include_router(clients.router, prefix=api_prefix)
    app.include_router(trading_platforms.router, prefix=api_prefix)
    app.include_router(items.router, prefix=api_prefix)
    app.include_router(gold.router, prefix=api_prefix)

    return app


app = create_app()
