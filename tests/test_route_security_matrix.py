from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.core.permissions import Role
from poi_admin.core.security import hash_password
from poi_admin.identity.models import Membership, Tenant, User
from poi_admin.operations.models import IntegrationOperation
from poi_admin.webhooks.models import WebhookEvent

# ruff: noqa: E501


async def _login(
    client: AsyncClient,
    email: str = "admin@example.com",
    password: str = "correct-horse-battery-staple",
) -> tuple[str, str | None]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    payload = response.json()
    csrf = response.cookies["poi_csrf"]
    if payload["tenants"]:
        return csrf, payload["tenants"][0]["tenant_id"]
    if email == "admin@example.com":
        created = await client.post(
            "/api/v1/platform/tenants",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Route Security Tenant", "slug": "route-security"},
        )
        assert created.status_code == 201
        return csrf, created.json()["id"]
    return csrf, None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/connections",
        "/api/v1/operations",
        "/api/v1/webhook-events",
        "/api/v1/local-life/orders",
        "/api/v1/local-life/vouchers",
        "/api/v1/local-life/after-sales",
        "/api/v1/local-life/funds",
        "/api/v1/local-life/bills",
        "/api/v1/local-life/accounting/reconciliation",
    ],
)
async def test_protected_gets_require_authentication(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/connections", {"capability": "local_life", "mode": "mock"}),
        ("/api/v1/operations/missing/retry", None),
        ("/api/v1/webhook-events/missing/retry", None),
        (
            "/api/v1/local-life/orders/sync",
            {
                "connection_id": "missing",
                "external_order_id": "order-1",
                "idempotency_key": "route-1",
            },
        ),
        ("/api/v1/local-life/vouchers/missing/consume", {"store_id": "store-1"}),
        ("/api/v1/local-life/vouchers/missing/revoke", {}),
        (
            "/api/v1/local-life/after-sales/sync",
            {
                "order_id": "missing",
                "external_after_sale_id": "after-1",
                "idempotency_key": "after-route-1",
            },
        ),
        (
            "/api/v1/local-life/accounting/sync",
            {"connection_id": "missing", "idempotency_key": "account-route-1"},
        ),
    ],
)
async def test_mutating_routes_require_csrf(
    client: AsyncClient, path: str, payload: dict[str, object] | None
) -> None:
    csrf, tenant_id = await _login(client)
    del csrf
    headers = {"X-Tenant-ID": tenant_id} if tenant_id else {}
    response = await client.post(path, headers=headers, json=payload)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_failed"


@pytest.mark.asyncio
async def test_operator_cannot_manage_connections_but_can_view_operations(
    client: AsyncClient,
) -> None:
    _, tenant_id = await _login(client, "operator@example.com", "operator-password")
    assert tenant_id is not None
    denied = await client.get("/api/v1/connections", headers={"X-Tenant-ID": tenant_id})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"
    allowed = await client.get("/api/v1/operations", headers={"X-Tenant-ID": tenant_id})
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_verifier_cannot_read_accounting(client: AsyncClient) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        verifier = User(
            email="verifier-route@example.com",
            display_name="Route verifier",
            password_hash=hash_password("verifier-password"),
        )
        session.add(verifier)
        await session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=verifier.id, role=Role.VERIFIER.value))
        await session.commit()
        tenant_id = tenant.id
    _, selected = await _login(client, "verifier-route@example.com", "verifier-password")
    assert selected == tenant_id
    response = await client.get(
        "/api/v1/local-life/accounting/reconciliation", headers={"X-Tenant-ID": tenant_id}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_connection_operation_and_webhook_routes_are_cross_tenant_scoped(
    client: AsyncClient,
) -> None:
    csrf, _ = await _login(client)
    tenant_a = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Tenant A", "slug": "route-a"},
    )
    tenant_b = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Tenant B", "slug": "route-b"},
    )
    tenant_a_id, tenant_b_id = tenant_a.json()["id"], tenant_b.json()["id"]
    headers_a = {"X-Tenant-ID": tenant_a_id, "X-CSRF-Token": csrf}
    connection_response = await client.post(
        "/api/v1/connections",
        headers=headers_a,
        json={"capability": "local_life", "mode": "mock"},
    )
    assert connection_response.status_code == 201
    connection_id = connection_response.json()["id"]

    listed = await client.get("/api/v1/connections", headers={"X-Tenant-ID": tenant_b_id})
    assert listed.status_code == 200 and listed.json() == []
    leaked_update = await client.put(
        f"/api/v1/connections/{connection_id}/secrets",
        headers={"X-Tenant-ID": tenant_b_id, "X-CSRF-Token": csrf},
        json={"callback_token": "should-not-write"},
    )
    assert leaked_update.status_code == 404
    assert leaked_update.json()["detail"]["code"] == "connection_not_found"

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        operation = IntegrationOperation(
            tenant_id=tenant_a_id,
            command_type="test",
            idempotency_key="a" * 64,
            payload={},
            status="failed",
        )
        event = WebhookEvent(
            tenant_id=tenant_a_id,
            connection_id=connection_id,
            fingerprint="b" * 64,
            event_type="unknown",
            payload={},
            status="failed",
        )
        session.add_all([operation, event])
        await session.commit()
        operation_id, event_id = operation.id, event.id
    operations = await client.get("/api/v1/operations", headers={"X-Tenant-ID": tenant_b_id})
    assert operations.status_code == 200 and operations.json() == []
    retry_operation = await client.post(
        f"/api/v1/operations/{operation_id}/retry",
        headers={"X-Tenant-ID": tenant_b_id, "X-CSRF-Token": csrf},
    )
    assert retry_operation.status_code == 404
    events = await client.get("/api/v1/webhook-events", headers={"X-Tenant-ID": tenant_b_id})
    assert events.status_code == 200 and events.json() == []
    retry_event = await client.post(
        f"/api/v1/webhook-events/{event_id}/retry",
        headers={"X-Tenant-ID": tenant_b_id, "X-CSRF-Token": csrf},
    )
    assert retry_event.status_code == 404


@pytest.mark.asyncio
async def test_operation_and_webhook_retry_routes_return_updated_state(client: AsyncClient) -> None:
    csrf, tenant_id = await _login(client)
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        connection = WeChatConnection(
            tenant_id=tenant_id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.flush()
        operation = IntegrationOperation(
            tenant_id=tenant_id,
            connection_id=connection.id,
            command_type="route.retry",
            idempotency_key="d" * 64,
            payload={},
            status="failed",
        )
        failed_event = WebhookEvent(
            tenant_id=tenant_id,
            connection_id=connection.id,
            fingerprint="e" * 64,
            event_type="order",
            payload={},
            status="failed",
        )
        processed_event = WebhookEvent(
            tenant_id=tenant_id,
            connection_id=connection.id,
            fingerprint="f" * 64,
            event_type="order",
            payload={},
            status="processed",
        )
        session.add_all([operation, failed_event, processed_event])
        await session.commit()
        operation_id, failed_event_id, processed_event_id = (
            operation.id,
            failed_event.id,
            processed_event.id,
        )

    headers = {"X-Tenant-ID": tenant_id}
    operations = await client.get("/api/v1/operations", headers=headers)
    assert operations.status_code == 200
    assert operations.json()[0]["id"] == operation_id
    retried_operation = await client.post(
        f"/api/v1/operations/{operation_id}/retry",
        headers={**headers, "X-CSRF-Token": csrf},
    )
    assert retried_operation.status_code == 200
    assert retried_operation.json()["status"] == "queued"

    events = await client.get("/api/v1/webhook-events", headers=headers)
    assert events.status_code == 200
    assert {item["id"] for item in events.json()} == {
        failed_event_id,
        processed_event_id,
    }
    retried_event = await client.post(
        f"/api/v1/webhook-events/{failed_event_id}/retry",
        headers={**headers, "X-CSRF-Token": csrf},
    )
    assert retried_event.status_code == 200
    assert retried_event.json()["status"] == "received"
    rejected_event = await client.post(
        f"/api/v1/webhook-events/{processed_event_id}/retry",
        headers={**headers, "X-CSRF-Token": csrf},
    )
    assert rejected_event.status_code == 409
    assert rejected_event.json()["detail"]["code"] == "webhook_not_retryable"
