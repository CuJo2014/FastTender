"""Общие фикстуры для тестов."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from fasttender.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
