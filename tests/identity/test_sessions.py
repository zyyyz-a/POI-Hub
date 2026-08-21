from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.identity.models import UserSession


@pytest.mark.asyncio
async def test_login_uses_opaque_hashed_session_cookie_and_csrf(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )

    assert response.status_code == 200
    assert response.cookies.get("poi_session")
    assert response.cookies.get("poi_csrf")
    assert len(response.cookies["poi_session"]) > 30
    assert response.cookies["poi_session"] != response.cookies["poi_csrf"]
    assert "password" not in response.json()

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        stored = (await session.execute(select(UserSession))).scalars().one()
        assert stored.token_hash != response.cookies["poi_session"]
        assert len(stored.token_hash) == 64
        assert stored.csrf_token_hash != response.cookies["poi_csrf"]


@pytest.mark.asyncio
async def test_mutating_request_requires_matching_csrf_token(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200

    missing = await client.post("/api/v1/auth/logout")
    assert missing.status_code == 403
    assert missing.json()["detail"]["code"] == "csrf_failed"

    valid = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": login.cookies["poi_csrf"]},
    )
    assert valid.status_code == 204


@pytest.mark.asyncio
async def test_expired_session_is_rejected(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        stored = (await session.execute(select(UserSession))).scalars().one()
        stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    response = await client.get("/api/v1/me")
    assert response.status_code == 401
