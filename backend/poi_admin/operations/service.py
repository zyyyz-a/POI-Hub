"""Transactional enqueue and leased-worker operation service."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.crypto import redact_secrets
from poi_admin.connections.ports import GatewayError

from .models import IntegrationOperation, OperationStatus, utcnow


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    code: str
    message: str
    retryable: bool


def classify_error(error: BaseException) -> ClassifiedError:
    if isinstance(error, GatewayError):
        return ClassifiedError(error.code, str(error), error.retryable)
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return ClassifiedError("upstream_unavailable", "上游服务暂时不可用", True)
    return ClassifiedError("operation_failed", "Operation failed; inspect server logs", False)


def backoff_seconds(attempt: int) -> float:
    delay = float(2 ** max(0, attempt - 1)) * 5.0 + random.uniform(0.0, 1.0)
    return min(3600.0, delay)


class OperationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> IntegrationOperation | None:
        stored_key = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return (
            await self.session.execute(
                select(IntegrationOperation).where(
                    IntegrationOperation.tenant_id == tenant_id,
                    IntegrationOperation.idempotency_key == stored_key,
                )
            )
        ).scalar_one_or_none()

    async def enqueue(
        self,
        tenant_id: str,
        command_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
        *,
        connection_id: str | None = None,
        resource_ref: str | None = None,
        max_attempts: int = 8,
    ) -> IntegrationOperation:
        stored_key = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        existing = await self.get_by_idempotency_key(tenant_id, idempotency_key)
        if existing is not None:
            return existing
        operation = IntegrationOperation(
            tenant_id=tenant_id,
            connection_id=connection_id,
            command_type=command_type,
            idempotency_key=stored_key,
            resource_ref=resource_ref,
            payload=cast(dict[str, Any], redact_secrets(payload)),
            max_attempts=max_attempts,
        )
        self.session.add(operation)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = (
                await self.session.execute(
                    select(IntegrationOperation).where(
                        IntegrationOperation.tenant_id == tenant_id,
                        IntegrationOperation.idempotency_key == stored_key,
                    )
                )
            ).scalar_one()
            return existing
        await self.session.refresh(operation)
        return operation

    async def get(self, tenant_id: str, operation_id: str) -> IntegrationOperation | None:
        return (
            await self.session.execute(
                select(IntegrationOperation).where(
                    IntegrationOperation.tenant_id == tenant_id,
                    IntegrationOperation.id == operation_id,
                )
            )
        ).scalar_one_or_none()

    async def claim(
        self, worker_id: str, *, lease_seconds: int = 60
    ) -> IntegrationOperation | None:
        now = utcnow()
        candidates = (
            (
                await self.session.execute(
                    select(IntegrationOperation)
                    .where(
                        or_(
                            and_(
                                IntegrationOperation.status.in_(
                                    [OperationStatus.QUEUED.value, OperationStatus.RETRY_WAIT.value]
                                ),
                                IntegrationOperation.next_attempt_at <= now,
                            ),
                            and_(
                                IntegrationOperation.status == OperationStatus.RUNNING.value,
                                IntegrationOperation.lease_expires_at.is_not(None),
                                IntegrationOperation.lease_expires_at <= now,
                            ),
                        )
                    )
                    .order_by(IntegrationOperation.created_at)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if candidates is None:
            return None
        claimed_id = (
            await self.session.execute(
                update(IntegrationOperation)
                .where(
                    IntegrationOperation.id == candidates.id,
                    or_(
                        and_(
                            IntegrationOperation.status.in_(
                                [OperationStatus.QUEUED.value, OperationStatus.RETRY_WAIT.value]
                            ),
                            IntegrationOperation.next_attempt_at <= now,
                        ),
                        and_(
                            IntegrationOperation.status == OperationStatus.RUNNING.value,
                            IntegrationOperation.lease_expires_at.is_not(None),
                            IntegrationOperation.lease_expires_at <= now,
                        ),
                    ),
                )
                .values(
                    status=OperationStatus.RUNNING.value,
                    worker_id=worker_id,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    attempt_count=IntegrationOperation.attempt_count + 1,
                )
                .execution_options(synchronize_session=False)
                .returning(IntegrationOperation.id)
            )
        ).scalar_one_or_none()
        await self.session.commit()
        if claimed_id is None:
            return None
        return (
            await self.session.execute(
                select(IntegrationOperation)
                .where(IntegrationOperation.id == claimed_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def mark_succeeded(
        self, operation: IntegrationOperation, response: dict[str, Any] | None = None
    ) -> None:
        operation.status = OperationStatus.SUCCEEDED.value
        operation.response_summary = (
            cast(dict[str, Any], redact_secrets(response)) if response is not None else None
        )
        operation.completed_at = utcnow()
        operation.lease_expires_at = None
        await self.session.commit()

    async def mark_failed(
        self, operation: IntegrationOperation, *, code: str, message: str, retryable: bool
    ) -> None:
        operation.error_code = code
        operation.error_message = message[:500]
        operation.lease_expires_at = None
        if retryable and operation.attempt_count < operation.max_attempts:
            operation.status = OperationStatus.RETRY_WAIT.value
            operation.next_attempt_at = utcnow() + timedelta(
                seconds=backoff_seconds(operation.attempt_count)
            )
        else:
            operation.status = OperationStatus.FAILED.value
            operation.completed_at = utcnow()
        await self.session.commit()

    async def manual_retry(self, tenant_id: str, operation_id: str) -> IntegrationOperation:
        operation = await self.get(tenant_id, operation_id)
        if operation is None:
            raise ValueError("operation not found")
        if operation.status not in {OperationStatus.FAILED.value, OperationStatus.RETRY_WAIT.value}:
            raise ValueError("operation is not retryable")
        operation.status = OperationStatus.QUEUED.value
        operation.next_attempt_at = utcnow()
        operation.error_code = None
        operation.error_message = None
        operation.completed_at = None
        operation.worker_id = None
        operation.attempt_count = 0
        await self.session.commit()
        await self.session.refresh(operation)
        return operation


__all__ = ["ClassifiedError", "OperationService", "backoff_seconds", "classify_error"]
