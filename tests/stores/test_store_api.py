from __future__ import annotations

import pytest
from httpx import AsyncClient


async def login_admin(client: AsyncClient) -> tuple[str, str]:
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    csrf = login.json()["csrf_token"]
    tenant = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "API 门店租户", "slug": "api-store-tenant"},
    )
    return csrf, tenant.json()["id"]


@pytest.mark.asyncio
async def test_store_crud_is_tenant_scoped(client: AsyncClient) -> None:
    csrf, tenant_id = await login_admin(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    created = await client.post(
        "/api/v1/stores",
        headers=headers,
        json={
            "code": "HZ-001",
            "name": "西湖门店",
            "contact_phone": "13800138000",
            "address": "杭州市西湖区孤山路1号",
            "latitude": 30.25,
            "longitude": 120.16,
        },
    )
    assert created.status_code == 201
    assert created.json()["contact_phone_masked"] == "****8000"
    assert "13800138000" not in created.text
    store_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/stores/{store_id}",
        headers=headers,
        json={"name": "西湖旗舰店", "version": 1},
    )
    listed = await client.get("/api/v1/stores", headers={"X-Tenant-ID": tenant_id})

    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert [item["name"] for item in listed.json()] == ["西湖旗舰店"]


@pytest.mark.asyncio
async def test_mock_poi_sync_only_suggests_then_human_confirms(client: AsyncClient) -> None:
    csrf, tenant_id = await login_admin(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    await client.post(
        "/api/v1/stores",
        headers=headers,
        json={
            "code": "HZ-001",
            "name": "西湖门店",
            "address": "杭州市西湖区孤山路1号",
            "latitude": 30.25,
            "longitude": 120.16,
        },
    )
    connection = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={"capability": "service_poi", "mode": "mock"},
    )
    assert connection.status_code == 201

    synced = await client.post(
        "/api/v1/pois/sync",
        headers=headers,
        json={"connection_id": connection.json()["id"]},
    )
    candidates = await client.get(
        "/api/v1/match-candidates", headers={"X-Tenant-ID": tenant_id}
    )
    mappings_before = await client.get(
        "/api/v1/store-poi-mappings", headers={"X-Tenant-ID": tenant_id}
    )

    assert synced.status_code == 200
    assert synced.json()["poi_count"] == 2
    assert candidates.json()
    assert mappings_before.json() == []

    confirmed = await client.post(
        f"/api/v1/match-candidates/{candidates.json()[0]['id']}/confirm", headers=headers
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["state"] == "active"
