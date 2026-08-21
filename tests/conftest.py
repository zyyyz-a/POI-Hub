from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from poi_admin.core.config import Settings
from poi_admin.main import create_app


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    database_path = tmp_path / "health.sqlite3"
    return Settings(
        database_url=f"sqlite+aiosqlite:///{database_path}",
        environment="test",
        secret_key="test-secret-key",
        encryption_key="test-encryption-key",
    )


@pytest_asyncio.fixture
async def client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    application = create_app(test_settings)
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client
