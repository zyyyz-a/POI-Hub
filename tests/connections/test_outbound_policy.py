from __future__ import annotations

import pytest

from poi_admin.connections.crypto import encrypt_secret_bundle
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.connections.service import ConnectionService


@pytest.mark.asyncio
async def test_tenant_secret_cannot_override_wechat_outbound_host(
    operation_service, tenant, test_settings
) -> None:
    connection = WeChatConnection(
        tenant_id=tenant.id,
        capability=Capability.LOCAL_LIFE.value,
        mode=ConnectionMode.LIVE.value,
        app_id="wx-app",
        encrypted_secrets=encrypt_secret_bundle(
            {
                "access_token": "token",
                "api_base_url": "http://169.254.169.254/latest/meta-data",
            },
            test_settings.encryption_key,
        ),
    )
    operation_service.session.add(connection)
    await operation_service.session.commit()

    gateway = await ConnectionService(
        operation_service.session, test_settings
    ).gateway(tenant.id, connection.id)

    assert gateway.http.base_url == "https://api.weixin.qq.com"  # type: ignore[attr-defined]
