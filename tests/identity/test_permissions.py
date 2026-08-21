from __future__ import annotations

import pytest
from httpx import AsyncClient

from poi_admin.core.permissions import Permission, Role, has_permission


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
    assert not has_permission(Role.OPERATOR, Permission.MANAGE_MEMBERS)
    assert not has_permission(Role.VERIFIER, Permission.MANAGE_PRODUCTS)
    assert not has_permission(Role.AUDITOR, Permission.CONSUME_VOUCHERS)


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
