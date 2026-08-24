from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.core.permissions import Permission, Role, has_permission
from poi_admin.identity.models import Membership, User


def test_fixed_roles_have_least_privilege_permissions() -> None:
    assert set(Role) == {
        Role.PLATFORM_ADMIN,
        Role.TENANT_ADMIN,
        Role.OPERATOR,
        Role.VERIFIER,
        Role.AUDITOR,
    }
    assert has_permission(Role.TENANT_ADMIN, Permission.MANAGE_MEMBERS)
    assert has_permission(Role.OPERATOR, Permission.MANAGE_STORES)
    assert has_permission(Role.VERIFIER, Permission.CONSUME_VOUCHERS)
    assert has_permission(Role.AUDITOR, Permission.VIEW_AUDIT)
    assert has_permission(Role.AUDITOR, Permission.VIEW_STORES)
    assert has_permission(Role.AUDITOR, Permission.VIEW_MAPPINGS)
    assert has_permission(Role.AUDITOR, Permission.VIEW_PRODUCTS)
    assert has_permission(Role.TENANT_ADMIN, Permission.VIEW_DASHBOARD)
    assert has_permission(Role.OPERATOR, Permission.VIEW_DASHBOARD)
    assert has_permission(Role.AUDITOR, Permission.VIEW_DASHBOARD)
    assert has_permission(Role.OPERATOR, Permission.VIEW_PRODUCTS)
    assert not has_permission(Role.OPERATOR, Permission.MANAGE_MEMBERS)
    assert not has_permission(Role.VERIFIER, Permission.MANAGE_PRODUCTS)
    assert not has_permission(Role.VERIFIER, Permission.VIEW_PRODUCTS)
    assert not has_permission(Role.VERIFIER, Permission.VIEW_DASHBOARD)
    assert not has_permission(Role.AUDITOR, Permission.CONSUME_VOUCHERS)
    assert has_permission(Role.OPERATOR, Permission.MANAGE_OPERATIONS)
    assert not has_permission(Role.VERIFIER, Permission.MANAGE_OPERATIONS)
    assert not has_permission(Role.AUDITOR, Permission.MANAGE_OPERATIONS)


@pytest.mark.asyncio
async def test_operator_cannot_manage_members(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@example.com", "password": "operator-password"},
    )
    assert login.status_code == 200
    tenant_id = login.json()["tenants"][0]["tenant_id"]
    response = await client.post(
        "/api/v1/members/invitations",
        headers={
            "X-Tenant-ID": tenant_id,
            "X-CSRF-Token": login.cookies["poi_csrf"],
        },
        json={"email": "new@example.com", "role": "operator"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_platform_admin_membership_cannot_downgrade_platform_role(
    client: AsyncClient,
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    csrf = login.cookies["poi_csrf"]
    tenant_response = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "平台成员租户", "slug": "platform-membership"},
    )
    tenant_id = tenant_response.json()["id"]
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        admin = (
            await session.execute(select(User).where(User.email == "admin@example.com"))
        ).scalar_one()
        session.add(
            Membership(
                tenant_id=tenant_id,
                user_id=admin.id,
                role=Role.OPERATOR.value,
                status="active",
            )
        )
        await session.commit()

    invitation = await client.post(
        "/api/v1/members/invitations",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json={"email": "platform-invite@example.com", "role": "auditor"},
    )
    assert invitation.status_code == 201
