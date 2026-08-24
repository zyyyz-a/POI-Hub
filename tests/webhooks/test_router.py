from __future__ import annotations

import hashlib
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.identity.models import Tenant
from poi_admin.webhooks.models import WebhookEvent


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
        json={"name": "回调路由租户", "slug": "webhook-router-tenant"},
    )
    return csrf, tenant.json()["id"]


@pytest.mark.asyncio
async def test_failed_webhook_can_be_requeued_by_tenant_operator(client: AsyncClient) -> None:
    csrf, tenant_id = await login_admin(client)
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.flush()
        event = WebhookEvent(
            tenant_id=tenant.id,
            connection_id=connection.id,
            fingerprint="r" * 64,
            event_type="product_audit",
            payload={"product_id": "missing", "status": "failed"},
            status="failed",
            attempt_count=2,
            error_message="上游暂时不可用",
        )
        session.add(event)
        await session.commit()
        event_id = event.id

    response = await client.post(
        f"/api/v1/webhook-events/{event_id}/retry",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "received"
    assert response.json()["attempt_count"] == 0


@pytest.mark.asyncio
async def test_public_callback_verification_ingest_and_deduplicates(client: AsyncClient) -> None:
    csrf, tenant_id = await login_admin(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    connection = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={
            "capability": "local_life",
            "mode": "mock",
            "secrets": {"callback_token": "callback-token"},
        },
    )
    assert connection.status_code == 201
    connection_id = connection.json()["id"]
    timestamp, nonce = "1700000000", "nonce-1"
    signature = hashlib.sha1(
        "".join(sorted(["callback-token", timestamp, nonce])).encode()
    ).hexdigest()
    query = {"timestamp": timestamp, "nonce": nonce, "signature": signature, "echostr": "echo-ok"}

    handshake = await client.get(f"/api/v1/callbacks/wechat/{connection_id}", params=query)
    assert handshake.status_code == 200
    assert handshake.text == "echo-ok"

    payload = {"Event": "order", "order_id": "order-callback-1"}
    callback_query = {
        "timestamp": timestamp,
        "nonce": nonce,
        "signature": signature,
    }
    first = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}",
        params=callback_query,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    second = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}",
        params=callback_query,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert first.status_code == second.status_code == 200

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        events = (
            await session.execute(
                select(WebhookEvent).where(WebhookEvent.connection_id == connection_id)
            )
        ).scalars().all()
    assert len(events) == 1
    assert events[0].event_type == "order"
