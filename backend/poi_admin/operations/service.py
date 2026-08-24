"""Transactional enqueue and leased-worker operation service."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.crypto import encrypt_secret_bundle, redact_secrets
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import GatewayError

from .models import IntegrationOperation, OperationStatus, utcnow


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    code: str
    message: str
    retryable: bool


class IdempotencyConflictError(ValueError):
    """The same tenant key was reused for a materially different command."""


@dataclass(frozen=True, slots=True)
class BatchRetryResult:
    operation_id: str
    accepted: bool
    reason: str | None = None


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
    def __init__(self, session: AsyncSession, encryption_key: str | None = None) -> None:
        self.session = session
        self.encryption_key = encryption_key

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
        if connection_id is not None:
            connection = (
                await self.session.execute(
                    select(WeChatConnection).where(
                        WeChatConnection.id == connection_id,
                        WeChatConnection.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if connection is None:
                raise ValueError("connection does not belong to tenant")
        if not idempotency_key.strip():
            raise ValueError("idempotency key must not be empty")
        stored_key = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        safe_payload = cast(dict[str, Any], redact_secrets(payload))
        encrypted_payload = (
            encrypt_secret_bundle(payload, self.encryption_key)
            if self.encryption_key is not None
            else None
        )
        existing = await self.get_by_idempotency_key(tenant_id, idempotency_key)
        if existing is not None:
            self._ensure_same_request(
                existing,
                command_type=command_type,
                connection_id=connection_id,
                payload=safe_payload,
                resource_ref=resource_ref,
            )
            return existing
        operation = IntegrationOperation(
            tenant_id=tenant_id,
            connection_id=connection_id,
            command_type=command_type,
            idempotency_key=stored_key,
            resource_ref=resource_ref,
            payload=safe_payload,
            encrypted_payload=encrypted_payload,
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
            self._ensure_same_request(
                existing,
                command_type=command_type,
                connection_id=connection_id,
                payload=safe_payload,
                resource_ref=resource_ref,
            )
            return existing
        await self.session.refresh(operation)
        return operation

    @staticmethod
    def _ensure_same_request(
        existing: IntegrationOperation,
        *,
        command_type: str,
        connection_id: str | None,
        payload: dict[str, Any],
        resource_ref: str | None,
    ) -> None:
        if (
            existing.command_type != command_type
            or existing.connection_id != connection_id
            or existing.payload != payload
            or existing.resource_ref != resource_ref
        ):
            raise IdempotencyConflictError("幂等键已用于其他操作")

    async def get(self, tenant_id: str, operation_id: str) -> IntegrationOperation | None:
        return (
            await self.session.execute(
                select(IntegrationOperation).where(
                    IntegrationOperation.tenant_id == tenant_id,
                    IntegrationOperation.id == operation_id,
                ).execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def claim(
        self, worker_id: str, *, lease_seconds: int = 60
    ) -> IntegrationOperation | None:
        now = utcnow()
        candidate_query = (
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
        bind = self.session.get_bind()
        if bind.dialect.name == "postgresql":
            candidate_query = candidate_query.with_for_update(skip_locked=True)
        candidates = (
            (
                await self.session.execute(candidate_query)
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

    async def renew_lease(
        self,
        operation_id: str,
        worker_id: str,
        *,
        lease_seconds: int,
    ) -> bool:
        """Extend a lease only while the same worker still owns the running operation."""

        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(IntegrationOperation)
                .where(
                    IntegrationOperation.id == operation_id,
                    IntegrationOperation.status == OperationStatus.RUNNING.value,
                    IntegrationOperation.worker_id == worker_id,
                )
                .values(lease_expires_at=utcnow() + timedelta(seconds=lease_seconds))
                .execution_options(synchronize_session=False)
            ),
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def mark_succeeded(
        self,
        operation: IntegrationOperation,
        response: dict[str, Any] | None = None,
        *,
        worker_id: str | None = None,
    ) -> None:
        owner = worker_id or operation.worker_id
        if owner is None:
            return
        response_summary = (
            cast(dict[str, Any], redact_secrets(response)) if response is not None else None
        )
        statement = update(IntegrationOperation).where(
            IntegrationOperation.id == operation.id,
            IntegrationOperation.status == OperationStatus.RUNNING.value,
        )
        if worker_id is not None:
            statement = statement.where(IntegrationOperation.worker_id == owner)
        await self.session.execute(
            statement
            .values(
                status=OperationStatus.SUCCEEDED.value,
                response_summary=response_summary,
                completed_at=utcnow(),
                lease_expires_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()

    async def mark_failed(
        self,
        operation: IntegrationOperation,
        *,
        code: str,
        message: str,
        retryable: bool,
        worker_id: str | None = None,
    ) -> None:
        owner = worker_id or operation.worker_id
        if owner is None:
            return
        next_status = OperationStatus.FAILED.value
        next_attempt: datetime | None = None
        completed_at: datetime | None = utcnow()
        if retryable and operation.attempt_count < operation.max_attempts:
            next_status = OperationStatus.RETRY_WAIT.value
            next_attempt = utcnow() + timedelta(
                seconds=backoff_seconds(operation.attempt_count)
            )
            completed_at = None
        statement = update(IntegrationOperation).where(
            IntegrationOperation.id == operation.id,
            IntegrationOperation.status == OperationStatus.RUNNING.value,
        )
        if worker_id is not None:
            statement = statement.where(IntegrationOperation.worker_id == owner)
        await self.session.execute(
            statement
            .values(
                status=next_status,
                error_code=code,
                error_message=message[:500],
                lease_expires_at=None,
                next_attempt_at=next_attempt or IntegrationOperation.next_attempt_at,
                completed_at=completed_at,
            )
            .execution_options(synchronize_session=False)
        )
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

    async def manual_retry_many(
        self, tenant_id: str, operation_ids: list[str]
    ) -> list[BatchRetryResult]:
        """Retry up to one bounded API batch with per-item results and one commit."""

        unique_ids = list(dict.fromkeys(operation_ids))
        rows = list(
            (
                await self.session.execute(
                    select(IntegrationOperation).where(
                        IntegrationOperation.tenant_id == tenant_id,
                        IntegrationOperation.id.in_(unique_ids),
                    ).execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        results: list[BatchRetryResult] = []
        for operation_id in unique_ids:
            operation = by_id.get(operation_id)
            if operation is None:
                results.append(BatchRetryResult(operation_id, False, "operation_not_found"))
                continue
            if operation.status not in {
                OperationStatus.FAILED.value,
                OperationStatus.RETRY_WAIT.value,
            }:
                results.append(BatchRetryResult(operation_id, False, "operation_not_retryable"))
                continue
            operation.status = OperationStatus.QUEUED.value
            operation.next_attempt_at = utcnow()
            operation.error_code = None
            operation.error_message = None
            operation.completed_at = None
            operation.worker_id = None
            operation.lease_expires_at = None
            operation.attempt_count = 0
            results.append(BatchRetryResult(operation_id, True))
        await self.session.commit()
        return results


__all__ = [
    "BatchRetryResult",
    "ClassifiedError",
    "IdempotencyConflictError",
    "OperationService",
    "backoff_seconds",
    "classify_error",
]
