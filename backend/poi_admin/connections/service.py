"""Connection configuration and gateway selection application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.config import Settings

from .crypto import decrypt_secret_bundle, encrypt_secret_bundle
from .mock import MockLocalLifeGateway, MockServicePoiGateway
from .models import WeChatConnection
from .ports import (
    AuthorizationState,
    Capability,
    ConnectionMode,
    GatewayTerminalError,
    LocalLifeGateway,
    ServicePoiGateway,
)


class ConnectionServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ConnectionPublic:
    id: str
    tenant_id: str
    capability: str
    mode: str
    status: str
    app_id: str | None
    merchant_id: str | None
    mock_scenario: str
    token_expires_at: datetime | None
    permission_snapshot: dict[str, Any] | None
    last_health_check_at: datetime | None
    last_error: str | None


class ConnectionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.http_client = http_client

    async def list(self, tenant_id: str) -> list[WeChatConnection]:
        result = await self.session.execute(
            select(WeChatConnection)
            .where(WeChatConnection.tenant_id == tenant_id)
            .order_by(WeChatConnection.created_at)
        )
        return list(result.scalars().all())

    async def get(self, tenant_id: str, connection_id: str) -> WeChatConnection | None:
        return (
            await self.session.execute(
                select(WeChatConnection).where(
                    WeChatConnection.tenant_id == tenant_id, WeChatConnection.id == connection_id
                )
            )
        ).scalar_one_or_none()

    async def create(
        self,
        tenant_id: str,
        *,
        capability: Capability,
        mode: ConnectionMode = ConnectionMode.MOCK,
        app_id: str | None = None,
        merchant_id: str | None = None,
        secrets: dict[str, str] | None = None,
        mock_scenario: str = "healthy",
    ) -> WeChatConnection:
        existing = (
            await self.session.execute(
                select(WeChatConnection).where(
                    WeChatConnection.tenant_id == tenant_id,
                    WeChatConnection.capability == capability.value,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConnectionServiceError("connection_exists", "该能力的连接已存在", 409)
        if mode == ConnectionMode.LIVE and not app_id:
            raise ConnectionServiceError("app_id_required", "真实连接必须提供 AppID", 422)
        connection = WeChatConnection(
            tenant_id=tenant_id,
            capability=capability.value,
            mode=mode.value,
            app_id=app_id,
            merchant_id=merchant_id,
            mock_scenario=mock_scenario,
            status=(
                AuthorizationState.AUTHORIZED.value
                if mode == ConnectionMode.MOCK
                else AuthorizationState.DISCONNECTED.value
            ),
        )
        if secrets:
            connection.encrypted_secrets = encrypt_secret_bundle(
                secrets, self.settings.encryption_key
            )
        self.session.add(connection)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConnectionServiceError("connection_exists", "该能力的连接已存在", 409) from exc
        await self.session.refresh(connection)
        return connection

    async def update_secrets(
        self, tenant_id: str, connection_id: str, secrets: dict[str, str]
    ) -> WeChatConnection:
        connection = await self.get(tenant_id, connection_id)
        if connection is None:
            raise ConnectionServiceError("connection_not_found", "连接不存在", 404)
        connection.encrypted_secrets = encrypt_secret_bundle(secrets, self.settings.encryption_key)
        await self.session.commit()
        await self.session.refresh(connection)
        return connection

    async def read_secrets(self, tenant_id: str, connection_id: str) -> dict[str, object]:
        connection = await self.get(tenant_id, connection_id)
        if connection is None:
            raise ConnectionServiceError("connection_not_found", "连接不存在", 404)
        if not connection.encrypted_secrets:
            return {}
        return decrypt_secret_bundle(connection.encrypted_secrets, self.settings.encryption_key)

    async def gateway(
        self, tenant_id: str, connection_id: str
    ) -> LocalLifeGateway | ServicePoiGateway:
        connection = await self.get(tenant_id, connection_id)
        if connection is None:
            raise ConnectionServiceError("connection_not_found", "连接不存在", 404)
        if connection.mode == ConnectionMode.MOCK.value:
            if connection.capability == Capability.LOCAL_LIFE.value:
                return MockLocalLifeGateway(tenant_id, scenario=connection.mock_scenario)
            return MockServicePoiGateway(tenant_id, scenario=connection.mock_scenario)
        if not connection.encrypted_secrets:
            raise GatewayTerminalError("真实微信连接凭据尚未配置", code="credentials_missing")
        from .local_life_live import LiveLocalLifeGateway
        from .service_poi_live import LiveServicePoiGateway
        from .tokens import token_provider_from_secrets

        secrets = decrypt_secret_bundle(connection.encrypted_secrets, self.settings.encryption_key)
        # The outbound target is platform-owned. Tenant-managed secrets must never
        # be able to turn an integration worker into an internal-network proxy.
        base_url = self.settings.wechat_api_base_url
        provider = token_provider_from_secrets(
            connection.app_id,
            secrets,
            base_url=base_url,
            http_client=self.http_client,
        )
        if connection.capability == Capability.LOCAL_LIFE.value:
            return LiveLocalLifeGateway(
                provider, base_url=base_url, http_client=self.http_client
            )
        if connection.capability == Capability.SERVICE_POI.value:
            try:
                district_id = int(secrets.get("district_id", 0))
            except (TypeError, ValueError):
                district_id = 0
            return LiveServicePoiGateway(
                provider,
                base_url=base_url,
                district_id=district_id,
                http_client=self.http_client,
            )
        raise GatewayTerminalError("连接能力无效", code="invalid_connection")

    @staticmethod
    def public(connection: WeChatConnection) -> ConnectionPublic:
        return ConnectionPublic(
            id=connection.id,
            tenant_id=connection.tenant_id,
            capability=connection.capability,
            mode=connection.mode,
            status=connection.status,
            app_id=connection.app_id,
            merchant_id=connection.merchant_id,
            mock_scenario=connection.mock_scenario,
            token_expires_at=connection.token_expires_at,
            permission_snapshot=connection.permission_snapshot,
            last_health_check_at=connection.last_health_check_at,
            last_error=connection.last_error,
        )


__all__ = ["ConnectionPublic", "ConnectionService", "ConnectionServiceError"]
