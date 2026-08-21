from typing import Annotated

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.database import get_session
from poi_admin.main import create_app


@pytest.mark.asyncio
async def test_get_session_can_be_used_as_fastapi_dependency(test_settings) -> None:
    application = create_app(test_settings)

    @application.get("/session-check")
    async def session_check_with_resources(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, int]:
        result = await session.execute(text("SELECT 1"))
        return {"value": int(result.scalar_one())}

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/session-check")

    assert response.status_code == 200
    assert response.json() == {"value": 1}
