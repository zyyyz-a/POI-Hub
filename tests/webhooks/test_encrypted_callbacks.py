from __future__ import annotations

import hashlib
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.connections.models import WeChatConnection
from poi_admin.local_life.models import LocalProduct, ProductStatus
from poi_admin.operations.worker import OperationWorker
from poi_admin.webhooks.crypto import encrypt_message
from poi_admin.webhooks.models import WebhookEvent

AES_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
CALLBACK_TOKEN = "callback-token"


def _signature(token: str, timestamp: str, nonce: str, encrypted: str | None = None) -> str:
    values = [token, timestamp, nonce] + ([encrypted] if encrypted is not None else [])
    return hashlib.sha1("".join(sorted(values)).encode()).hexdigest()


async def _live_connection(client: AsyncClient) -> tuple[str, str, str]:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    csrf = login.json()["csrf_token"]
    created_tenant = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Encrypted callback tenant", "slug": "encrypted-callback-tenant"},
    )
    assert created_tenant.status_code == 201, created_tenant.text
    tenant_id = created_tenant.json()["id"]
    response = await client.post(
        "/api/v1/connections",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json={
            "capability": "local_life",
            "mode": "live",
            "app_id": "wx-test",
            "secrets": {"callback_token": CALLBACK_TOKEN, "encoding_aes_key": AES_KEY},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], tenant_id, csrf


@pytest.mark.asyncio
async def test_encrypted_callback_is_verified_decrypted_and_processed(client: AsyncClient) -> None:
    connection_id, tenant_id, _ = await _live_connection(client)
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        connection = (
            await session.execute(
                select(WeChatConnection).where(WeChatConnection.id == connection_id)
            )
        ).scalar_one()
        product = LocalProduct(
            tenant_id=tenant_id,
            connection_id=connection.id,
            merchant_product_id="merchant-1",
            external_product_id="external-1",
            name="套餐",
            remote_status=ProductStatus.DRAFT.value,
        )
        session.add(product)
        await session.commit()
        product_id = product.id

    timestamp, nonce = "1700000000", "nonce-encrypted"
    payload = {"Event": "product_listed", "product_id": "external-1"}
    encrypted = encrypt_message(json.dumps(payload, ensure_ascii=False), AES_KEY, "wx-test")
    response = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}",
        params={
            "timestamp": timestamp,
            "nonce": nonce,
            "msg_signature": _signature(CALLBACK_TOKEN, timestamp, nonce, encrypted),
        },
        json={"Encrypt": encrypted},
    )
    assert response.status_code == 200
    assert response.text == "success"

    async with database.session_factory() as session:
        event = (
            await session.execute(
                select(WebhookEvent).where(WebhookEvent.connection_id == connection_id)
            )
        ).scalar_one()
        assert event.payload == payload
        assert event.status == "received"
        worker = OperationWorker(session, handlers={})
        await worker.run_once()
        refreshed = (
            await session.execute(select(LocalProduct).where(LocalProduct.id == product_id))
        ).scalar_one()
        assert refreshed.remote_status == ProductStatus.LISTED.value
        assert refreshed.version == 2
        assert (
            await session.execute(select(WebhookEvent).where(WebhookEvent.id == event.id))
        ).scalar_one().status == "processed"


@pytest.mark.asyncio
async def test_encrypted_callback_rejects_missing_or_invalid_signature(client: AsyncClient) -> None:
    connection_id, _, _ = await _live_connection(client)
    encrypted = encrypt_message('{"Event":"order"}', AES_KEY, "wx-test")
    base = {"timestamp": "1700000000", "nonce": "nonce"}

    missing = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}", params=base, json={"Encrypt": encrypted}
    )
    assert (
        missing.status_code == 403
        and missing.json()["detail"]["code"] == "invalid_callback_signature"
    )

    invalid = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}",
        params={**base, "msg_signature": "0" * 40},
        json={"Encrypt": encrypted},
    )
    assert (
        invalid.status_code == 403
        and invalid.json()["detail"]["code"] == "invalid_callback_signature"
    )


@pytest.mark.asyncio
async def test_encrypted_callback_rejects_wrong_app_id_and_malformed_ciphertext(
    client: AsyncClient,
) -> None:
    connection_id, _, _ = await _live_connection(client)
    timestamp, nonce = "1700000000", "nonce"
    wrong_app = encrypt_message('{"Event":"order"}', AES_KEY, "wx-other")
    wrong_response = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}",
        params={
            "timestamp": timestamp,
            "nonce": nonce,
            "msg_signature": _signature(CALLBACK_TOKEN, timestamp, nonce, wrong_app),
        },
        json={"Encrypt": wrong_app},
    )
    assert wrong_response.status_code == 400
    assert wrong_response.json()["detail"]["code"] == "invalid_callback_payload"

    malformed = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}",
        params={
            "timestamp": timestamp,
            "nonce": nonce,
            "msg_signature": _signature(CALLBACK_TOKEN, timestamp, nonce, "bad"),
        },
        json={"Encrypt": "bad"},
    )
    assert malformed.status_code == 400
    assert malformed.json()["detail"]["code"] == "invalid_callback_payload"


@pytest.mark.asyncio
async def test_plaintext_callback_validates_json_signature_and_body_limit(
    client: AsyncClient,
) -> None:
    connection_id, _, _ = await _live_connection(client)
    timestamp, nonce = "1700000000", "nonce"
    base = {"timestamp": timestamp, "nonce": nonce}

    missing = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}", params=base, content=b"{}"
    )
    assert (
        missing.status_code == 403
        and missing.json()["detail"]["code"] == "invalid_callback_signature"
    )

    signature = _signature(CALLBACK_TOKEN, timestamp, nonce)
    malformed = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}",
        params={**base, "signature": signature},
        content=b"not-json",
    )
    assert (
        malformed.status_code == 400
        and malformed.json()["detail"]["code"] == "invalid_callback_payload"
    )

    non_object = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}",
        params={**base, "signature": signature},
        content=b"[]",
    )
    assert (
        non_object.status_code == 400
        and non_object.json()["detail"]["code"] == "invalid_callback_payload"
    )

    oversized = await client.post(
        f"/api/v1/callbacks/wechat/{connection_id}",
        params=base,
        content=b"x" * (512 * 1024 + 1),
    )
    assert oversized.status_code == 413


@pytest.mark.asyncio
async def test_callback_connection_and_secret_configuration_errors(client: AsyncClient) -> None:
    not_found = await client.post(
        "/api/v1/callbacks/wechat/not-found",
        params={"timestamp": "1", "nonce": "n", "signature": "s"},
        json={},
    )
    assert (
        not_found.status_code == 404
        and not_found.json()["detail"]["code"] == "connection_not_found"
    )

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    csrf = login.json()["csrf_token"]
    created_tenant = await client.post(
        "/api/v1/platform/tenants",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Callback error tenant", "slug": "callback-error-tenant"},
    )
    assert created_tenant.status_code == 201, created_tenant.text
    tenant_id = created_tenant.json()["id"]
    connection = await client.post(
        "/api/v1/connections",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json={"capability": "local_life", "mode": "mock", "secrets": {}},
    )
    assert connection.status_code == 201
    response = await client.get(
        f"/api/v1/callbacks/wechat/{connection.json()['id']}",
        params={"timestamp": "1", "nonce": "n", "signature": "s", "echostr": "echo"},
    )
    assert (
        response.status_code == 503
        and response.json()["detail"]["code"] == "callback_not_configured"
    )
