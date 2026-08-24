"""Callback verification, sanitization, and idempotent inbox persistence."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.crypto import (
    decrypt_secret_bundle,
    encrypt_secret_bundle,
    redact_secrets,
)
from poi_admin.connections.models import WeChatConnection
from poi_admin.core.config import Settings

from .crypto import decrypt_message, verify_signature
from .models import WebhookEvent


class WebhookServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class WebhookService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def connection(self, connection_id: str) -> WeChatConnection:
        row = (
            await self.session.execute(
                select(WeChatConnection).where(WeChatConnection.id == connection_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise WebhookServiceError("connection_not_found", "连接不存在", 404)
        return row

    def callback_secrets(self, connection: WeChatConnection) -> dict[str, Any]:
        if not connection.encrypted_secrets:
            raise WebhookServiceError("callback_not_configured", "回调密钥尚未配置", 503)
        return decrypt_secret_bundle(connection.encrypted_secrets, self.settings.encryption_key)

    def verify(
        self,
        connection: WeChatConnection,
        *,
        token: str,
        timestamp: str,
        nonce: str,
        signature: str,
        encrypt: str | None = None,
    ) -> None:
        secrets = self.callback_secrets(connection)
        expected_token = str(secrets.get("callback_token", secrets.get("token", "")))
        if not expected_token or not verify_signature(
            expected_token, timestamp, nonce, signature, encrypt
        ):
            raise WebhookServiceError("invalid_callback_signature", "回调签名无效", 403)

    async def ingest(
        self, connection_id: str, payload: dict[str, Any]
    ) -> tuple[WebhookEvent, bool]:
        connection = await self.connection(connection_id)
        full_canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        fingerprint = hashlib.sha256(full_canonical.encode("utf-8")).hexdigest()
        safe = redact_secrets(payload)
        if not isinstance(safe, dict):
            safe = {"payload": safe}
        existing = (
            await self.session.execute(
                select(WebhookEvent).where(
                    WebhookEvent.connection_id == connection.id,
                    WebhookEvent.fingerprint == fingerprint,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, True
        row = WebhookEvent(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            fingerprint=fingerprint,
            event_type=str(payload.get("Event", payload.get("event", "unknown"))),
            payload=safe,
            encrypted_payload=encrypt_secret_bundle(payload, self.settings.encryption_key),
            max_attempts=self.settings.webhook_max_attempts,
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = (
                await self.session.execute(
                    select(WebhookEvent).where(
                        WebhookEvent.connection_id == connection.id,
                        WebhookEvent.fingerprint == fingerprint,
                    )
                )
            ).scalar_one()
            return existing, True
        await self.session.refresh(row)
        return row, False

    async def retry(self, tenant_id: str, event_id: str) -> WebhookEvent:
        event = (
            await self.session.execute(
                select(WebhookEvent).where(
                    WebhookEvent.tenant_id == tenant_id,
                    WebhookEvent.id == event_id,
                )
            )
        ).scalar_one_or_none()
        if event is None:
            raise WebhookServiceError("webhook_not_found", "回调事件不存在", 404)
        if event.status not in {"failed", "retry_wait", "dead_letter", "received"}:
            raise WebhookServiceError("webhook_not_retryable", "该回调已处理完成", 409)
        event.status = "received"
        event.attempt_count = 0
        event.next_attempt_at = event.received_at
        event.error_message = None
        event.worker_id = None
        event.lease_expires_at = None
        await self.session.commit()
        await self.session.refresh(event)
        return event

    def decrypt_payload(self, connection: WeChatConnection, encrypted: str) -> dict[str, Any]:
        secrets = self.callback_secrets(connection)
        app_id = connection.app_id or str(secrets.get("app_id", ""))
        message = decrypt_message(encrypted, str(secrets.get("encoding_aes_key", "")), app_id)
        try:
            value = json.loads(message)
        except json.JSONDecodeError as error:
            raise WebhookServiceError(
                "invalid_callback_payload", "回调内容不是有效 JSON", 400
            ) from error
        if not isinstance(value, dict):
            raise WebhookServiceError("invalid_callback_payload", "回调内容格式无效", 400)
        return value


__all__ = ["WebhookService", "WebhookServiceError"]
