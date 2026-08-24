from __future__ import annotations

from datetime import timedelta

import pytest

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode, GatewayTransientError
from poi_admin.identity.models import Tenant
from poi_admin.operations.models import OperationStatus
from poi_admin.operations.service import (
    IdempotencyConflictError,
    OperationService,
    backoff_seconds,
    classify_error,
)
from poi_admin.operations.worker import OperationWorker


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_returns_existing(operation_service, tenant) -> None:
    first = await operation_service.enqueue(tenant.id, "sync_pois", "sync:pois:1", {})
    second = await operation_service.enqueue(tenant.id, "sync_pois", "sync:pois:1", {})
    assert second.id == first.id


@pytest.mark.asyncio
async def test_idempotency_key_reuse_rejects_different_request(operation_service, tenant) -> None:
    await operation_service.enqueue(tenant.id, "sync_pois", "sync:conflict", {"page": 1})
    with pytest.raises(IdempotencyConflictError, match="幂等键"):
        await operation_service.enqueue(
            tenant.id, "sync_pois", "sync:conflict", {"page": 2}
        )


@pytest.mark.asyncio
async def test_claim_lease_and_manual_retry(operation_service, tenant) -> None:
    operation = await operation_service.enqueue(tenant.id, "sync_pois", "lease:1", {})
    claimed = await operation_service.claim("worker-a", lease_seconds=30)
    assert claimed is not None and claimed.id == operation.id
    assert claimed.status == OperationStatus.RUNNING
    assert await operation_service.claim("worker-b", lease_seconds=30) is None
    await operation_service.mark_failed(
        claimed, code="validation_error", message="bad", retryable=False
    )
    await operation_service.manual_retry(tenant.id, operation.id)
    refreshed = await operation_service.get(tenant.id, operation.id)
    assert refreshed is not None and refreshed.status == OperationStatus.QUEUED
    assert refreshed.attempt_count == 0


@pytest.mark.asyncio
async def test_worker_can_renew_owned_lease(operation_service, tenant) -> None:
    operation = await operation_service.enqueue(tenant.id, "sync", "lease:renew", {})
    claimed = await operation_service.claim("worker-a", lease_seconds=30)
    assert claimed is not None
    original_expiry = claimed.lease_expires_at
    assert await operation_service.renew_lease(
        operation.id, "worker-a", lease_seconds=120
    )
    assert not await operation_service.renew_lease(
        operation.id, "worker-b", lease_seconds=120
    )
    refreshed = await operation_service.get(tenant.id, operation.id)
    assert refreshed is not None
    assert refreshed.lease_expires_at is not None
    assert original_expiry is not None
    assert refreshed.lease_expires_at > original_expiry


@pytest.mark.asyncio
async def test_batch_retry_returns_per_item_outcomes(operation_service, tenant) -> None:
    failed = await operation_service.enqueue(tenant.id, "sync", "batch:failed", {})
    claimed = await operation_service.claim("worker-a")
    assert claimed is not None
    await operation_service.mark_failed(
        claimed, code="terminal", message="failed", retryable=False
    )
    queued = await operation_service.enqueue(tenant.id, "sync", "batch:queued", {})

    results = await operation_service.manual_retry_many(
        tenant.id, [failed.id, queued.id, "missing", failed.id]
    )

    assert [(item.operation_id, item.accepted, item.reason) for item in results] == [
        (failed.id, True, None),
        (queued.id, False, "operation_not_retryable"),
        ("missing", False, "operation_not_found"),
    ]


@pytest.mark.asyncio
async def test_operation_diagnostics_are_redacted(operation_service, tenant) -> None:
    operation = await operation_service.enqueue(
        tenant.id, "sync", "redact:1", {"access_token": "secret", "name": "safe"}
    )
    assert operation.payload == {"access_token": "[REDACTED]", "name": "safe"}
    claimed = await operation_service.claim("worker")
    await operation_service.mark_succeeded(claimed, {"phone": "13800138000"})
    refreshed = await operation_service.get(tenant.id, operation.id)
    assert refreshed is not None
    assert refreshed.response_summary == {"phone": "[REDACTED]"}


@pytest.mark.asyncio
async def test_encrypted_operation_payload_is_decrypted_only_for_handler(
    operation_service, tenant, test_settings
) -> None:
    secure_service = OperationService(
        operation_service.session, test_settings.encryption_key
    )
    operation = await secure_service.enqueue(
        tenant.id,
        "secure",
        "secure:payload:1",
        {"contract_phone": "13800138000", "name": "门店"},
    )
    assert operation.payload["contract_phone"] == "[REDACTED]"
    assert operation.encrypted_payload is not None
    assert "13800138000" not in operation.encrypted_payload
    received: dict[str, object] = {}

    async def handler(item):
        received.update(item.payload)
        return {"ok": True}

    worker = OperationWorker(
        operation_service.session,
        settings=test_settings,
        handlers={"secure": handler},
    )
    completed = await worker.run_once()

    assert completed is not None and completed.status == OperationStatus.SUCCEEDED
    assert received["contract_phone"] == "13800138000"
    refreshed = await secure_service.get(tenant.id, operation.id)
    assert refreshed is not None
    assert refreshed.payload["contract_phone"] == "[REDACTED]"


def test_retry_classification_and_bounded_backoff() -> None:
    assert classify_error(TimeoutError("timeout")).retryable
    assert not classify_error(ValueError("invalid")).retryable
    assert backoff_seconds(1) < backoff_seconds(4) <= 3600


@pytest.mark.asyncio
async def test_expired_lease_can_be_reclaimed(operation_service, tenant) -> None:
    operation = await operation_service.enqueue(tenant.id, "sync", "expired:1", {})
    claimed = await operation_service.claim("worker-a", lease_seconds=-1)
    assert claimed is not None
    reclaimed = await operation_service.claim("worker-b", lease_seconds=30)
    assert reclaimed is not None and reclaimed.id == operation.id
    assert reclaimed.worker_id == "worker-b"
    assert reclaimed.attempt_count == 2


@pytest.mark.asyncio
async def test_stale_worker_cannot_complete_reclaimed_operation(operation_service, tenant) -> None:
    operation = await operation_service.enqueue(tenant.id, "sync", "stale-worker:1", {})
    claimed = await operation_service.claim("worker-a", lease_seconds=30)
    assert claimed is not None
    claimed.worker_id = "worker-b"
    await operation_service.session.commit()

    await operation_service.mark_succeeded(claimed, {"stale": True}, worker_id="worker-a")
    refreshed = await operation_service.get(tenant.id, operation.id)
    assert refreshed is not None
    assert refreshed.status == OperationStatus.RUNNING
    assert refreshed.worker_id == "worker-b"
    assert refreshed.response_summary is None


@pytest.mark.asyncio
async def test_enqueue_rejects_connection_from_another_tenant(operation_service, tenant) -> None:
    other = Tenant(name="Connection Owner", slug="connection-owner")
    operation_service.session.add(other)
    await operation_service.session.flush()
    connection = WeChatConnection(
        tenant_id=other.id,
        capability=Capability.LOCAL_LIFE.value,
        mode=ConnectionMode.MOCK.value,
    )
    operation_service.session.add(connection)
    await operation_service.session.commit()

    with pytest.raises(ValueError, match="connection does not belong to tenant"):
        await operation_service.enqueue(
            tenant.id,
            "sync",
            "wrong-connection-tenant",
            {},
            connection_id=connection.id,
        )


@pytest.mark.asyncio
async def test_idempotency_key_is_tenant_scoped_and_hashed(operation_service, tenant) -> None:
    other = Tenant(name="Other", slug="other-operations")
    operation_service.session.add(other)
    await operation_service.session.commit()
    first = await operation_service.enqueue(tenant.id, "sync", "sensitive-business-key", {})
    second = await operation_service.enqueue(other.id, "sync", "sensitive-business-key", {})
    assert first.id != second.id
    assert first.idempotency_key != "sensitive-business-key"


@pytest.mark.asyncio
async def test_worker_schedules_transient_errors_and_stops_terminal_errors(
    operation_service, tenant
) -> None:
    transient = await operation_service.enqueue(tenant.id, "transient", "worker:1", {})

    async def transient_handler(_operation):
        raise GatewayTransientError("temporary", code="rate_limited")

    worker = OperationWorker(operation_service.session, handlers={"transient": transient_handler})
    await worker.run_once()
    refreshed = await operation_service.get(tenant.id, transient.id)
    assert refreshed is not None and refreshed.status == OperationStatus.RETRY_WAIT
    assert refreshed.error_code == "rate_limited"

    terminal = await operation_service.enqueue(tenant.id, "terminal", "worker:2", {})

    async def terminal_handler(_operation):
        raise ValueError("secret detail must not leak")

    worker.handlers["terminal"] = terminal_handler
    transient.next_attempt_at = transient.next_attempt_at + timedelta(days=1)
    await operation_service.session.commit()
    await worker.run_once()
    failed = await operation_service.get(tenant.id, terminal.id)
    assert failed is not None and failed.status == OperationStatus.FAILED
    assert "secret detail" not in (failed.error_message or "")
