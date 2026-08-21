from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.core.permissions import Role
from poi_admin.core.security import hash_password
from poi_admin.identity.models import Membership, Tenant, User
from poi_admin.operations.worker import OperationWorker
from poi_admin.stores.service import StoreService, StoreServiceError


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

    rejected_null = await client.patch(
        f"/api/v1/stores/{store_id}",
        headers=headers,
        json={"name": None, "version": 2},
    )
    assert rejected_null.status_code == 422


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

    sync_payload = {
        "connection_id": connection.json()["id"],
        "idempotency_key": "test-poi-sync-1",
    }
    synced = await client.post(
        "/api/v1/pois/sync",
        headers=headers,
        json=sync_payload,
    )
    duplicate = await client.post(
        "/api/v1/pois/sync", headers=headers, json=sync_payload
    )
    candidates_before_worker = await client.get(
        "/api/v1/match-candidates", headers={"X-Tenant-ID": tenant_id}
    )

    assert synced.status_code == 202
    assert synced.json()["status"] == "queued"
    assert duplicate.json()["operation_id"] == synced.json()["operation_id"]
    assert candidates_before_worker.json() == []

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    settings = client._transport.app.state.settings  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        worker = OperationWorker(session, settings=settings)
        operation = await worker.run_once()
        assert operation is not None
        assert operation.status == "succeeded"
    assert operation.response_summary == {"poi_count": 2, "candidate_count": 2}

    unsupported_connection = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={"capability": "local_life", "mode": "mock"},
    )
    unsupported_sync = await client.post(
        "/api/v1/pois/sync",
        headers=headers,
        json={
            "connection_id": unsupported_connection.json()["id"],
            "idempotency_key": "test-invalid-poi-sync",
        },
    )
    assert unsupported_sync.status_code == 422

    candidates = await client.get(
        "/api/v1/match-candidates", headers={"X-Tenant-ID": tenant_id}
    )
    mappings_before = await client.get(
        "/api/v1/store-poi-mappings", headers={"X-Tenant-ID": tenant_id}
    )

    assert candidates.json()
    assert mappings_before.json() == []

    confirmed = await client.post(
        f"/api/v1/match-candidates/{candidates.json()[0]['id']}/confirm", headers=headers
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["state"] == "active"


@pytest.mark.asyncio
async def test_store_version_update_is_atomic_across_sessions(client: AsyncClient) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as setup_session:
        tenant = (
            await setup_session.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one()
        store = await StoreService(setup_session).create_store(
            tenant.id, code="ATOMIC-1", name="并发门店", address="测试地址"
        )
        store_id = store.id

    async with (
        database.session_factory() as first_session,
        database.session_factory() as second_session,
    ):
        first_service = StoreService(first_session)
        second_service = StoreService(second_session)
        assert (await first_service.get_store(tenant.id, store_id)).version == 1  # type: ignore[union-attr]
        assert (await second_service.get_store(tenant.id, store_id)).version == 1  # type: ignore[union-attr]

        await first_service.update_store(tenant.id, store_id, 1, {"name": "首次更新"})
        with pytest.raises(StoreServiceError) as conflict:
            await second_service.update_store(
                tenant.id, store_id, 1, {"name": "过期覆盖"}
            )

        assert conflict.value.code == "version_conflict"


@pytest.mark.asyncio
async def test_auditor_can_read_store_workspace_but_cannot_write(client: AsyncClient) -> None:
    csrf, tenant_id = await login_admin(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    await client.post(
        "/api/v1/stores",
        headers=headers,
        json={"code": "AUDIT-1", "name": "审计门店", "address": "审计地址"},
    )
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        auditor = User(
            email="store-auditor@example.com",
            display_name="门店审计员",
            password_hash=hash_password("auditor-password"),
        )
        session.add(auditor)
        await session.flush()
        session.add(
            Membership(
                tenant_id=tenant_id, user_id=auditor.id, role=Role.AUDITOR.value
            )
        )
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": auditor.email, "password": "auditor-password"},
    )
    read_headers = {"X-Tenant-ID": tenant_id}
    for path in ("/stores", "/pois", "/match-candidates", "/store-poi-mappings"):
        assert (await client.get(f"/api/v1{path}", headers=read_headers)).status_code == 200
    denied = await client.post(
        "/api/v1/stores",
        headers={
            **read_headers,
            "X-CSRF-Token": login.json()["csrf_token"],
        },
        json={"code": "DENIED", "name": "禁止写入", "address": "地址"},
    )
    assert denied.status_code == 403
    denied_dismiss = await client.post(
        "/api/v1/match-candidates/missing/dismiss",
        headers={**read_headers, "X-CSRF-Token": login.json()["csrf_token"]},
    )
    assert denied_dismiss.status_code == 403
