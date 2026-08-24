from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.core.permissions import Role
from poi_admin.core.security import hash_password
from poi_admin.identity.models import Membership, Tenant, User
from poi_admin.operations.worker import OperationWorker
from poi_admin.stores.models import StorePoiMapping
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
    dismissed = await client.post(
        f"/api/v1/match-candidates/{candidates.json()[1]['id']}/dismiss",
        headers=headers,
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["dismissed_at"] is not None

    confirmed = await client.post(
        f"/api/v1/match-candidates/{candidates.json()[0]['id']}/confirm", headers=headers
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["state"] == "active"


@pytest.mark.asyncio
async def test_mapping_command_api_enforces_csrf_and_reports_cross_conflict(
    client: AsyncClient,
) -> None:
    csrf, tenant_id = await login_admin(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        actor = (
            await session.execute(select(User).where(User.is_platform_admin.is_(True)))
        ).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant_id,
            capability=Capability.SERVICE_POI.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        service = StoreService(session)
        first = await service.create_store(
            tenant_id, code="API-CROSS-A", name="Store A", address="Address A"
        )
        second = await service.create_store(
            tenant_id, code="API-CROSS-B", name="Store B", address="Address B"
        )
        pois = await service.sync_pois(tenant_id, connection, actor_user_id=actor.id)
        first_store_id, second_store_id = first.id, second.id
        first_poi_id, second_poi_id = pois[0].id, pois[1].id

    first_mapping_payload = {
        "store_id": first_store_id,
        "service_poi_id": first_poi_id,
    }
    missing_csrf = await client.post(
        "/api/v1/store-poi-mappings/manual",
        headers={"X-Tenant-ID": tenant_id},
        json=first_mapping_payload,
    )
    assert missing_csrf.status_code == 403

    first_mapping = await client.post(
        "/api/v1/store-poi-mappings/manual",
        headers=headers,
        json=first_mapping_payload,
    )
    second_mapping = await client.post(
        "/api/v1/store-poi-mappings/manual",
        headers=headers,
        json={"store_id": second_store_id, "service_poi_id": second_poi_id},
    )
    assert first_mapping.status_code == 201
    assert second_mapping.status_code == 201

    cross_conflict = await client.post(
        "/api/v1/store-poi-mappings/manual",
        headers=headers,
        json={"store_id": first_store_id, "service_poi_id": second_poi_id},
    )
    assert cross_conflict.status_code == 409
    assert cross_conflict.json()["detail"]["code"] == "mapping_conflict"

    mapping_id = first_mapping.json()["id"]
    missing_unbind_csrf = await client.post(
        f"/api/v1/store-poi-mappings/{mapping_id}/unbind",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert missing_unbind_csrf.status_code == 403
    unbound = await client.post(
        f"/api/v1/store-poi-mappings/{mapping_id}/unbind", headers=headers
    )
    assert unbound.status_code == 200
    assert unbound.json()["state"] == "unbound"


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
async def test_store_rejects_blank_identifiers_and_archive_is_versioned_and_unbinds(
    client: AsyncClient,
) -> None:
    csrf, tenant_id = await login_admin(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    blank = await client.post(
        "/api/v1/stores",
        headers=headers,
        json={"code": "   ", "name": "门店", "address": "地址"},
    )
    assert blank.status_code == 422

    created = await client.post(
        "/api/v1/stores",
        headers=headers,
        json={"code": "ARCHIVE-1", "name": "归档门店", "address": "归档地址"},
    )
    assert created.status_code == 201
    store_id = created.json()["id"]
    stale = await client.delete(
        f"/api/v1/stores/{store_id}?version=99", headers=headers
    )
    assert stale.status_code == 409

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        actor = (
            await session.execute(select(User).where(User.is_platform_admin.is_(True)))
        ).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.SERVICE_POI.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        service = StoreService(session)
        store = await service.get_store(tenant_id, store_id)
        assert store is not None
        pois = await service.sync_pois(tenant_id, connection, actor_user_id=actor.id)
        mapping = await service.manual_map(tenant_id, store_id, pois[0].id, actor.id)
        version = store.version
        await service.archive_store(tenant_id, store_id, version, actor.id)
        refreshed = await service.get_store(tenant_id, store_id)
        assert refreshed is not None and refreshed.status == "inactive"
        mapping_row = await session.get(StorePoiMapping, mapping.id)
        assert mapping_row is not None and mapping_row.state == "unbound"


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
    denied_manual = await client.post(
        "/api/v1/store-poi-mappings/manual",
        headers={**read_headers, "X-CSRF-Token": login.json()["csrf_token"]},
        json={"store_id": "missing", "service_poi_id": "missing"},
    )
    denied_unbind = await client.post(
        "/api/v1/store-poi-mappings/missing/unbind",
        headers={**read_headers, "X-CSRF-Token": login.json()["csrf_token"]},
    )
    assert denied_manual.status_code == 403
    assert denied_unbind.status_code == 403
