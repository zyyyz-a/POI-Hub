from __future__ import annotations

import pytest
from httpx import AsyncClient

from poi_admin.operations.worker import OperationWorker


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
        json={"name": "POI 命令租户", "slug": "poi-command-tenant"},
    )
    return csrf, tenant.json()["id"]


@pytest.mark.asyncio
async def test_create_poi_is_durable_and_persists_remote_mirror(client: AsyncClient) -> None:
    csrf, tenant_id = await login_admin(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    connection = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={"capability": "service_poi", "mode": "mock"},
    )
    assert connection.status_code == 201

    payload = {
        "connection_id": connection.json()["id"],
        "idempotency_key": "poi-create-1",
        "name": "新湖门店",
        "address": "杭州市西湖区新湖路 3 号",
        "latitude": 30.251,
        "longitude": 120.161,
        "map_poi_id": "map-poi-new-lake",
        "pic_list": ["https://example.com/store.jpg"],
        "contract_phone": "13800138000",
        "hour": "09:00-21:00",
        "credential": "license-1",
    }
    created = await client.post("/api/v1/pois", headers=headers, json=payload)
    duplicate = await client.post("/api/v1/pois", headers=headers, json=payload)

    assert created.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json()["operation_id"] == created.json()["operation_id"]

    conflicting = await client.post(
        "/api/v1/pois",
        headers=headers,
        json={**payload, "name": "同一键不同请求"},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"]["code"] == "idempotency_key_conflict"

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    settings = client._transport.app.state.settings  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        operation = await OperationWorker(session, settings=settings).run_once()
        assert operation is not None
        assert operation.status == "succeeded"

    pois = await client.get("/api/v1/pois", headers={"X-Tenant-ID": tenant_id})
    assert pois.status_code == 200
    assert any(item["name"] == "新湖门店" for item in pois.json())


@pytest.mark.asyncio
async def test_poi_update_delete_and_audit_refresh_are_durable(client: AsyncClient) -> None:
    csrf, tenant_id = await login_admin(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    connection = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={"capability": "service_poi", "mode": "mock"},
    )
    connection_id = connection.json()["id"]
    created = await client.post(
        "/api/v1/pois",
        headers=headers,
        json={
            "connection_id": connection_id,
            "idempotency_key": "poi-create-commands",
            "name": "待更新门店",
            "address": "杭州市西湖区测试路 1 号",
            "map_poi_id": "map-poi-command",
            "pic_list": ["https://example.com/store.jpg"],
            "contract_phone": "13800138000",
            "hour": "09:00-21:00",
            "credential": "license-1",
        },
    )
    assert created.status_code == 202
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    settings = client._transport.app.state.settings  # type: ignore[attr-defined]

    async with database.session_factory() as session:
        await OperationWorker(session, settings=settings).run_once()
    poi = (await client.get("/api/v1/pois", headers={"X-Tenant-ID": tenant_id})).json()[0]

    updated = await client.patch(
        f"/api/v1/pois/{poi['id']}",
        headers=headers,
        json={"idempotency_key": "poi-update-commands", "name": "已更新门店"},
    )
    assert updated.status_code == 202
    async with database.session_factory() as session:
        await OperationWorker(session, settings=settings).run_once()
    refreshed = (await client.get("/api/v1/pois", headers={"X-Tenant-ID": tenant_id})).json()[0]
    assert refreshed["name"] == "已更新门店"

    audit = await client.post(
        f"/api/v1/pois/{poi['id']}/audit-refresh",
        headers=headers,
        json={"idempotency_key": "poi-audit-commands"},
    )
    assert audit.status_code == 202
    async with database.session_factory() as session:
        await OperationWorker(session, settings=settings).run_once()

    deleted = await client.post(
        f"/api/v1/pois/{poi['id']}/delete",
        headers=headers,
        json={"idempotency_key": "poi-delete-commands"},
    )
    assert deleted.status_code == 202
    async with database.session_factory() as session:
        await OperationWorker(session, settings=settings).run_once()
    final = (await client.get("/api/v1/pois", headers={"X-Tenant-ID": tenant_id})).json()[0]
    assert final["remote_status"] == "deleted"


@pytest.mark.asyncio
async def test_poi_search_is_tenant_scoped_and_uses_connection(client: AsyncClient) -> None:
    csrf, tenant_id = await login_admin(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    connection = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={"capability": "service_poi", "mode": "mock"},
    )
    response = await client.get(
        "/api/v1/pois/search",
        headers={"X-Tenant-ID": tenant_id},
        params={"connection_id": connection.json()["id"], "keyword": "西湖"},
    )
    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["西湖门店"]
