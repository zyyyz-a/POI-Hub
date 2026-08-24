from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.identity.models import Membership, Tenant, User


@pytest.mark.asyncio
async def test_invitation_acceptance_creates_membership_and_selected_tenant(
    client: AsyncClient,
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    csrf = login.cookies["poi_csrf"]
    create_tenant = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "杭州门店", "slug": "hangzhou"},
    )
    assert create_tenant.status_code == 201
    tenant_id = create_tenant.json()["id"]

    invitation = await client.post(
        "/api/v1/members/invitations",
        headers={"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id},
        json={"email": "operator@example.com", "role": "operator"},
    )
    assert invitation.status_code == 201
    invite_token = invitation.json()["invite_token"]

    accepted = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": invite_token,
            "password": "operator-password-123",
            "display_name": "运营员",
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["membership"]["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_cross_tenant_members_are_not_visible(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    csrf = login.cookies["poi_csrf"]
    first = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "一号租户", "slug": "tenant-one"},
    )
    second = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "二号租户", "slug": "tenant-two"},
    )
    first_id, second_id = first.json()["id"], second.json()["id"]

    invite = await client.post(
        "/api/v1/members/invitations",
        headers={"X-CSRF-Token": csrf, "X-Tenant-ID": first_id},
        json={"email": "first@example.com", "role": "auditor"},
    )
    assert invite.status_code == 201
    accepted = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": invite.json()["invite_token"],
            "password": "auditor-password",
            "display_name": "只读审计员",
        },
    )
    assert accepted.status_code == 201

    first_members = await client.get("/api/v1/members", headers={"X-Tenant-ID": first_id})
    second_members = await client.get("/api/v1/members", headers={"X-Tenant-ID": second_id})
    assert first_members.status_code == 200
    assert second_members.status_code == 200
    assert [item["email"] for item in first_members.json()] == ["first@example.com"]
    assert second_members.json() == []


@pytest.mark.asyncio
async def test_acceptance_rejects_suspended_tenant(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    csrf = login.cookies["poi_csrf"]
    created = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "待停用租户", "slug": "suspended-tenant"},
    )
    tenant_id = created.json()["id"]
    invitation = await client.post(
        "/api/v1/members/invitations",
        headers={"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id},
        json={"email": "suspended-user@example.com", "role": "operator"},
    )
    assert invitation.status_code == 201

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        tenant.status = "suspended"
        await session.commit()

    accepted = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": invitation.json()["invite_token"],
            "password": "suspended-password",
            "display_name": "停用租户用户",
        },
    )
    assert accepted.status_code == 403
    assert accepted.json()["detail"]["code"] == "tenant_inactive"


@pytest.mark.asyncio
async def test_platform_admin_can_suspend_and_restore_tenant(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    csrf = login.cookies["poi_csrf"]
    created = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "主控状态租户", "slug": "controlled-status"},
    )
    tenant_id = created.json()["id"]

    suspended = await client.patch(
        f"/api/v1/platform/tenants/{tenant_id}/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "suspended"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"

    blocked = await client.get("/api/v1/dashboard", headers={"X-Tenant-ID": tenant_id})
    assert blocked.status_code == 404
    assert blocked.json()["detail"]["code"] == "tenant_not_found"

    restored = await client.patch(
        f"/api/v1/platform/tenants/{tenant_id}/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "active"},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"


@pytest.mark.asyncio
async def test_tenant_member_cannot_use_platform_status_control(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@example.com", "password": "operator-password"},
    )
    tenant_id = login.json()["tenants"][0]["tenant_id"]
    response = await client.patch(
        f"/api/v1/platform/tenants/{tenant_id}/status",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": login.cookies["poi_csrf"]},
        json={"status": "suspended"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_multiple_memberships_require_explicit_tenant_selection(client: AsyncClient) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        operator = (
            await session.execute(select(User).where(User.email == "operator@example.com"))
        ).scalar_one()
        second_tenant = Tenant(name="第二租户", slug="second-membership")
        session.add(second_tenant)
        await session.flush()
        session.add(
            Membership(
                tenant_id=second_tenant.id,
                user_id=operator.id,
                role="operator",
                status="active",
            )
        )
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@example.com", "password": "operator-password"},
    )
    assert len(login.json()["tenants"]) == 2
    response = await client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json()["tenant"] is None
    assert {item["tenant_id"] for item in response.json()["tenants"]} == {
        item["tenant_id"] for item in login.json()["tenants"]
    }

    dashboard = await client.get("/api/v1/dashboard")
    assert dashboard.status_code == 400
    assert dashboard.json()["detail"]["code"] == "tenant_required"
