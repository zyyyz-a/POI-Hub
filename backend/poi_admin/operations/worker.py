"""One-process durable operation worker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import timedelta
from typing import Any, cast

import httpx
from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import set_committed_value

from poi_admin.audit.service import AuditService
from poi_admin.connections.crypto import decrypt_secret_bundle
from poi_admin.core.config import Settings
from poi_admin.webhooks.models import WebhookEvent

from .models import IntegrationOperation, utcnow
from .service import OperationService, backoff_seconds, classify_error

Handler = Callable[[IntegrationOperation], Awaitable[dict[str, Any] | None]]
logger = logging.getLogger("poi_admin.worker")


async def process_webhook_event(
    session: AsyncSession, event: WebhookEvent, settings: Settings | None = None
) -> str:
    """Import lazily so operation handler modules can reuse the worker Handler type."""
    from poi_admin.webhooks.handlers import process_webhook_event as process

    return await process(session, event, settings)


class OperationWorker:
    def __init__(
        self,
        session: AsyncSession,
        *,
        worker_id: str = "worker-1",
        settings: Settings | None = None,
        handlers: dict[str, Handler] | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        lease_seconds: int | None = None,
        prefer_webhook: bool = True,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.worker_id = worker_id
        self.session_factory = session_factory
        self.lease_seconds = lease_seconds or (
            settings.worker_lease_seconds if settings is not None else 120
        )
        self.webhook_max_attempts = (
            settings.webhook_max_attempts if settings is not None else 8
        )
        self.prefer_webhook = prefer_webhook
        self.processed_last_cycle = False
        if handlers is None:
            if settings is None:
                raise ValueError("settings are required for application operation handlers")
            from poi_admin.local_life.accounting import accounting_operation_handlers
            from poi_admin.local_life.orders import order_operation_handlers
            from poi_admin.local_life.products import product_operation_handlers
            from poi_admin.local_life.vouchers import voucher_operation_handlers
            from poi_admin.stores.operations import store_operation_handlers

            handlers = store_operation_handlers(
                session, settings, http_client=http_client
            )
            handlers.update(
                product_operation_handlers(session, settings, http_client=http_client)
            )
            handlers.update(
                order_operation_handlers(session, settings, http_client=http_client)
            )
            handlers.update(
                voucher_operation_handlers(session, settings, http_client=http_client)
            )
            handlers.update(
                accounting_operation_handlers(session, settings, http_client=http_client)
            )
        self.handlers = handlers

    async def run_once(self) -> IntegrationOperation | None:
        self.processed_last_cycle = False
        if self.prefer_webhook and await self._run_webhook_once():
            self.processed_last_cycle = True
            return None
        service = OperationService(self.session)
        operation = await service.claim(self.worker_id, lease_seconds=self.lease_seconds)
        if operation is None:
            if not self.prefer_webhook and await self._run_webhook_once():
                self.processed_last_cycle = True
            return None
        self.processed_last_cycle = True
        handler = self.handlers.get(operation.command_type)
        if handler is None:
            await service.mark_failed(
                operation,
                code="handler_not_found",
                message="未配置操作处理器",
                retryable=False,
                worker_id=self.worker_id,
            )
            await AuditService(self.session).record(
                tenant_id=operation.tenant_id,
                actor_user_id=None,
                action="integration_operation.failed",
                resource_type="integration_operation",
                resource_id=operation.id,
                after={"status": "failed", "error_code": "handler_not_found"},
            )
            return operation
        heartbeat = self._start_heartbeat("operation", operation.id)
        try:
            try:
                safe_payload = operation.payload
                try:
                    if operation.encrypted_payload:
                        if self.settings is None:
                            raise RuntimeError(
                                "settings are required to decrypt operation payload"
                            )
                        set_committed_value(
                            operation,
                            "payload",
                            decrypt_secret_bundle(
                                operation.encrypted_payload, self.settings.encryption_key
                            ),
                        )
                    result = await handler(operation)
                finally:
                    set_committed_value(operation, "payload", safe_payload)
            except asyncio.CancelledError:
                # A graceful process shutdown must not strand a claimed operation
                # in a running state until its lease expires. Return it to the
                # durable retry queue before propagating cancellation to the caller.
                await service.mark_failed(
                    operation,
                    code="worker_shutdown",
                    message="Worker is shutting down; operation will be retried",
                    retryable=True,
                    worker_id=self.worker_id,
                )
                raise
            except Exception as error:  # boundary sanitizes all handler errors
                logger.exception(
                    "operation_failed operation_id=%s tenant_id=%s command=%s worker_id=%s",
                    operation.id,
                    operation.tenant_id,
                    operation.command_type,
                    self.worker_id,
                )
                classified = classify_error(error)
                await service.mark_failed(
                    operation,
                    code=classified.code,
                    message=classified.message,
                    retryable=classified.retryable,
                    worker_id=self.worker_id,
                )
                await AuditService(self.session).record(
                    tenant_id=operation.tenant_id,
                    actor_user_id=None,
                    action="integration_operation.failed",
                    resource_type="integration_operation",
                    resource_id=operation.id,
                    after={"status": "failed", "error_code": classified.code},
                )
            else:
                await service.mark_succeeded(operation, result, worker_id=self.worker_id)
                await AuditService(self.session).record(
                    tenant_id=operation.tenant_id,
                    actor_user_id=None,
                    action="integration_operation.succeeded",
                    resource_type="integration_operation",
                    resource_id=operation.id,
                    after={"status": "succeeded", "command_type": operation.command_type},
                )
        finally:
            await self._stop_heartbeat(heartbeat)
        await self.session.refresh(operation)
        return operation

    async def _run_webhook_once(self) -> bool:
        event = await self._claim_webhook()
        if event is None:
            return False
        heartbeat = self._start_heartbeat("webhook", event.id)
        try:
            try:
                await process_webhook_event(self.session, event, self.settings)
            except asyncio.CancelledError:
                await self._mark_webhook_failed(event, "Worker is shutting down")
                raise
            except Exception:
                logger.exception(
                    "webhook_failed event_id=%s tenant_id=%s worker_id=%s",
                    event.id,
                    event.tenant_id,
                    self.worker_id,
                )
                await self._mark_webhook_failed(
                    event, "Webhook processing failed; inspect server logs"
                )
        finally:
            await self._stop_heartbeat(heartbeat)
        return True

    async def _claim_webhook(self) -> WebhookEvent | None:
        now = utcnow()
        candidate_query = (
            select(WebhookEvent)
            .where(
                or_(
                    and_(
                        WebhookEvent.status.in_(["received", "retry_wait", "failed"]),
                        WebhookEvent.next_attempt_at <= now,
                    ),
                    and_(
                        WebhookEvent.status == "processing",
                        WebhookEvent.lease_expires_at.is_not(None),
                        WebhookEvent.lease_expires_at <= now,
                    ),
                )
            )
            .order_by(WebhookEvent.received_at, WebhookEvent.id)
            .limit(1)
        )
        bind = self.session.get_bind()
        if bind.dialect.name == "postgresql":
            candidate_query = candidate_query.with_for_update(skip_locked=True)
        candidate = (
            await self.session.execute(candidate_query)
        ).scalar_one_or_none()
        if candidate is None:
            return None
        claimed_id = (
            await self.session.execute(
                update(WebhookEvent)
                .where(
                    WebhookEvent.id == candidate.id,
                    or_(
                        and_(
                            WebhookEvent.status.in_(["received", "retry_wait", "failed"]),
                            WebhookEvent.next_attempt_at <= now,
                        ),
                        and_(
                            WebhookEvent.status == "processing",
                            WebhookEvent.lease_expires_at.is_not(None),
                            WebhookEvent.lease_expires_at <= now,
                        ),
                    ),
                )
                .values(
                    status="processing",
                    worker_id=self.worker_id,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    attempt_count=WebhookEvent.attempt_count + 1,
                )
                .execution_options(synchronize_session=False)
                .returning(WebhookEvent.id)
            )
        ).scalar_one_or_none()
        await self.session.commit()
        if claimed_id is None:
            return None
        return (
            await self.session.execute(
                select(WebhookEvent)
                .where(WebhookEvent.id == claimed_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def _mark_webhook_failed(self, event: WebhookEvent, message: str) -> None:
        terminal = event.attempt_count >= min(event.max_attempts, self.webhook_max_attempts)
        values: dict[str, Any] = {
            "status": "dead_letter" if terminal else "retry_wait",
            "error_message": message[:500],
            "worker_id": None,
            "lease_expires_at": None,
        }
        if not terminal:
            values["next_attempt_at"] = utcnow() + timedelta(
                seconds=backoff_seconds(event.attempt_count)
            )
        await self.session.execute(
            update(WebhookEvent)
            .where(
                WebhookEvent.id == event.id,
                WebhookEvent.status == "processing",
                WebhookEvent.worker_id == self.worker_id,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        for field, value in values.items():
            setattr(event, field, value)
        await self.session.commit()

    def _start_heartbeat(self, kind: str, resource_id: str) -> asyncio.Task[None] | None:
        if self.session_factory is None:
            return None
        return asyncio.create_task(self._heartbeat(kind, resource_id))

    async def _stop_heartbeat(self, task: asyncio.Task[None] | None) -> None:
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _heartbeat(self, kind: str, resource_id: str) -> None:
        assert self.session_factory is not None
        interval = max(10.0, self.lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            async with self.session_factory() as heartbeat_session:
                if kind == "operation":
                    renewed = await OperationService(heartbeat_session).renew_lease(
                        resource_id,
                        self.worker_id,
                        lease_seconds=self.lease_seconds,
                    )
                else:
                    result = cast(
                        CursorResult[Any],
                        await heartbeat_session.execute(
                            update(WebhookEvent)
                            .where(
                                WebhookEvent.id == resource_id,
                                WebhookEvent.status == "processing",
                                WebhookEvent.worker_id == self.worker_id,
                            )
                            .values(
                                lease_expires_at=utcnow()
                                + timedelta(seconds=self.lease_seconds)
                            )
                        ),
                    )
                    await heartbeat_session.commit()
                    renewed = bool(result.rowcount)
            if not renewed:
                return


__all__ = ["Handler", "OperationWorker"]
