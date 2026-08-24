from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import ASGITransport, AsyncClient

from poi_admin.core.config import Settings
from poi_admin.core.licensing import LicenseClaims, canonical_claims, load_license
from poi_admin.main import create_app


def _licensed_settings(tmp_path, *, expired: bool = False) -> Settings:
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    claims = LicenseClaims(
        license_id="license-1",
        customer_id="customer-1",
        customer_name="测试客户",
        installation_id="install-1",
        issued_at=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) + timedelta(days=-1 if expired else 30),
        max_stores=20,
        features=["poi", "batch"],
    )
    envelope = {
        "claims": claims.model_dump(mode="json"),
        "signature": base64.b64encode(private_key.sign(canonical_claims(claims))).decode(),
    }
    license_path = tmp_path / "license.json"
    license_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    return Settings(
        environment="test",
        deployment_mode="appliance",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'license.sqlite3'}",
        secret_key="test-secret",
        encryption_key="test-encryption",
        installation_id="install-1",
        license_mode="enforce",
        license_path=license_path,
        license_public_key=base64.b64encode(public_bytes).decode(),
    )


def test_valid_offline_license_is_verified(tmp_path) -> None:
    state = load_license(_licensed_settings(tmp_path))

    assert state.current_status() == "valid"
    assert state.allows_writes()
    assert state.claims is not None and state.claims.max_stores == 20


@pytest.mark.asyncio
async def test_expired_enforced_license_keeps_reads_but_blocks_business_writes(tmp_path) -> None:
    application = create_app(_licensed_settings(tmp_path, expired=True))

    @application.get("/api/v1/business-check")
    async def read_business() -> dict[str, bool]:
        return {"ok": True}

    @application.post("/api/v1/business-check")
    async def write_business() -> dict[str, bool]:
        return {"ok": True}

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            readable = await client.get("/api/v1/business-check")
            blocked = await client.post("/api/v1/business-check")

    assert readable.status_code == 200
    assert blocked.status_code == 402
    assert blocked.json()["code"] == "license_write_disabled"
    assert blocked.headers["X-Request-ID"]
