from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.connections.crypto import (
    decrypt_secret_bundle,
    encrypt_secret_bundle,
    redact_secrets,
)
from poi_admin.connections.models import WeChatConnection


def test_aes_gcm_round_trip_and_ciphertext_hides_plaintext() -> None:
    payload = {"app_secret": "very-secret", "refresh_token": "token-value"}
    encrypted = encrypt_secret_bundle(payload, "test-master-key")
    assert "very-secret" not in encrypted
    assert decrypt_secret_bundle(encrypted, "test-master-key") == payload


def test_redaction_recursively_removes_secret_bearing_fields() -> None:
    value = {"access_token": "abc", "nested": {"phone": "13800138000", "name": "ok"}}
    redacted = redact_secrets(value)
    assert redacted == {
        "access_token": "[REDACTED]",
        "nested": {"phone": "[REDACTED]", "name": "ok"},
    }


@pytest.mark.asyncio
async def test_connection_api_encrypts_and_never_returns_secrets(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    from poi_admin.identity.models import Tenant

    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        tenant_id = tenant.id
    response = await client.post(
        "/api/v1/connections",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": login.cookies["poi_csrf"]},
        json={
            "capability": "local_life",
            "mode": "live",
            "app_id": "wx-test",
            "secrets": {"app_secret": "must-not-leak", "refresh_token": "also-secret"},
        },
    )
    assert response.status_code == 201
    assert "must-not-leak" not in response.text
    assert "refresh_token" not in response.text
    async with database.session_factory() as session:
        connection = (await session.execute(select(WeChatConnection))).scalar_one()
        assert connection.tenant_id == tenant_id
        assert connection.encrypted_secrets is not None
        assert "must-not-leak" not in connection.encrypted_secrets
