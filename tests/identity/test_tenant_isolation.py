from __future__ import annotations

import pytest
from httpx import AsyncClient


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
