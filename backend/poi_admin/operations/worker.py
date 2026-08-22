"""One-process durable operation worker."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.config import Settings

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
            from poi_admin.local_life.products import product_operation_handlers
            from poi_admin.stores.operations import store_operation_handlers

            handlers = store_operation_handlers(session, settings)
            handlers.update(product_operation_handlers(session, settings))
        self.handlers = handlers

    async def run_once(self) -> IntegrationOperation | None:
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
        else:
            await service.mark_succeeded(operation, result, worker_id=self.worker_id)
        return operation


__all__ = ["Handler", "OperationWorker"]
