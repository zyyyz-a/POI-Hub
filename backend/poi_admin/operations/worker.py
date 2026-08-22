"""One-process durable operation worker."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.audit.service import AuditService
from poi_admin.core.config import Settings
from poi_admin.webhooks.handlers import process_webhook_event
from poi_admin.webhooks.models import WebhookEvent

from .models import IntegrationOperation
from .service import OperationService, classify_error

Handler = Callable[[IntegrationOperation], Awaitable[dict[str, Any] | None]]


class OperationWorker:
    def __init__(
        self,
        session: AsyncSession,
        *,
        worker_id: str = "worker-1",
        settings: Settings | None = None,
        handlers: dict[str, Handler] | None = None,
    ) -> None:
        self.session = session
        self.worker_id = worker_id
        if handlers is None:
            if settings is None:
                raise ValueError("settings are required for application operation handlers")
            from poi_admin.local_life.accounting import accounting_operation_handlers
            from poi_admin.local_life.orders import order_operation_handlers
            from poi_admin.local_life.products import product_operation_handlers
            from poi_admin.local_life.vouchers import voucher_operation_handlers
            from poi_admin.stores.operations import store_operation_handlers

            handlers = store_operation_handlers(session, settings)
            handlers.update(product_operation_handlers(session, settings))
            handlers.update(order_operation_handlers(session, settings))
            handlers.update(voucher_operation_handlers(session, settings))
            handlers.update(accounting_operation_handlers(session, settings))
        self.handlers = handlers

    async def run_once(self) -> IntegrationOperation | None:
        if await self._run_webhook_once():
            return None
        service = OperationService(self.session)
        operation = await service.claim(self.worker_id)
        if operation is None:
            return None
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
        try:
            result = await handler(operation)
        except Exception as error:  # boundary sanitizes all handler errors
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
        await self.session.refresh(operation)
        return operation

    async def _run_webhook_once(self) -> bool:
        event = (
            await self.session.execute(
                select(WebhookEvent)
                .where(WebhookEvent.status.in_(["received", "failed"]))
                .order_by(WebhookEvent.received_at, WebhookEvent.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if event is None:
            return False
        try:
            await process_webhook_event(self.session, event)
        except Exception as error:  # callback failures stay visible and retryable
            event.status = "failed"
            event.attempt_count += 1
            event.error_message = str(error)[:500]
            await self.session.commit()
        return True


__all__ = ["Handler", "OperationWorker"]
