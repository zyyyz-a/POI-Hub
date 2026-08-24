from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from poi_admin.core.config import Settings
from poi_admin.core.orm import Base
from poi_admin.identity.models import Tenant
from poi_admin.identity.service import ensure_test_identity
from poi_admin.main import create_app
from poi_admin.operations.service import OperationService


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
        async with application.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with application.state.database.session_factory() as session:
            await ensure_test_identity(session)
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client


@pytest_asyncio.fixture
async def tenant(test_settings: Settings):
    application = create_app(test_settings)
    async with application.router.lifespan_context(application):
        async with application.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with application.state.database.session_factory() as session:
            await ensure_test_identity(session)
            tenant = (
                await session.execute(select(Tenant).where(Tenant.slug == "demo"))
            ).scalar_one()
            yield tenant


@pytest_asyncio.fixture
async def operation_service(test_settings: Settings):
    application = create_app(test_settings)
    async with application.router.lifespan_context(application):
        async with application.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with application.state.database.session_factory() as session:
            await ensure_test_identity(session)
            yield OperationService(session)
