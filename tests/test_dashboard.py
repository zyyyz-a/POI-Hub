from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.core.permissions import Role
from poi_admin.core.security import hash_password
from poi_admin.identity.models import Membership, Tenant, User


@pytest.mark.asyncio
async def test_verifier_cannot_view_dashboard(client: AsyncClient) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        verifier = User(
            email="dashboard-verifier@example.com",
            display_name="核销员",
            password_hash=hash_password("dashboard-verifier-password"),
        )
        session.add(verifier)
        await session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=verifier.id, role=Role.VERIFIER.value))
        await session.commit()
        tenant_id = tenant.id

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": verifier.email, "password": "dashboard-verifier-password"},
    )
    assert login.status_code == 200
    response = await client.get("/api/v1/dashboard", headers={"X-Tenant-ID": tenant_id})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"
