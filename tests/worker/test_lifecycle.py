from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

import poi_admin.worker as process_worker
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.operations.models import OperationStatus
from poi_admin.operations.worker import OperationWorker
from poi_admin.webhooks.models import WebhookEvent


class StopPolling(Exception):
    pass


class FakeSessionContext:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> object:
        self.entered += 1
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited += 1


class FakeDatabase:
    def __init__(self) -> None:
        self.context = FakeSessionContext()
        self.disposed = False

    def session_factory(self) -> FakeSessionContext:
        return self.context

    async def dispose(self) -> None:
        self.disposed = True


@pytest.mark.asyncio
async def test_process_worker_polls_with_floor_and_disposes_on_shutdown(monkeypatch) -> None:
    database = FakeDatabase()
    settings = object()
    sleeps: list[float] = []
    runs: list[object] = []

    class FakeOperationWorker:
        def __init__(self, session, *, settings, **kwargs) -> None:
            del kwargs
            runs.append((session, settings))
            self.processed_last_cycle = False

        async def run_once(self) -> None:
            return None

    async def stop_after_one(delay: float) -> None:
        sleeps.append(delay)
        raise StopPolling

    monkeypatch.setattr(process_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(process_worker, "create_database", lambda value: database)
    monkeypatch.setattr(process_worker, "OperationWorker", FakeOperationWorker)
    monkeypatch.setattr(process_worker.asyncio, "sleep", stop_after_one)

    with pytest.raises(StopPolling):
        await process_worker.run(-3)

    assert sleeps == [0.1]
    assert len(runs) == 1 and runs[0][1] is settings
    assert database.context.entered == database.context.exited == 1
    assert database.disposed is True


@pytest.mark.asyncio
async def test_process_worker_disposes_when_operation_worker_crashes(monkeypatch) -> None:
    database = FakeDatabase()

    class CrashingWorker:
        def __init__(self, session, *, settings, **kwargs) -> None:
            del session, settings, kwargs

        async def run_once(self) -> None:
            raise RuntimeError("worker failure")

    monkeypatch.setattr(process_worker, "get_settings", lambda: object())
    monkeypatch.setattr(process_worker, "create_database", lambda value: database)
    monkeypatch.setattr(process_worker, "OperationWorker", CrashingWorker)

    with pytest.raises(RuntimeError, match="worker failure"):
        await process_worker.run(1)
    assert database.context.entered == database.context.exited == 1
    assert database.disposed is True


@pytest.mark.asyncio
async def test_operation_worker_marks_handler_exception_failed_and_releases_lease(
    operation_service, tenant
) -> None:
    operation = await operation_service.enqueue(tenant.id, "boom", "worker-lifecycle:boom", {})

    async def boom(_operation):
        raise RuntimeError("private upstream detail")

    worker = OperationWorker(operation_service.session, handlers={"boom": boom})
    result = await worker.run_once()

    assert result is not None and result.id == operation.id
    refreshed = await operation_service.get(tenant.id, operation.id)
    assert refreshed is not None
    assert refreshed.status == OperationStatus.FAILED
    assert refreshed.error_code == "operation_failed"
    assert refreshed.error_message == "Operation failed; inspect server logs"
    assert refreshed.lease_expires_at is None
    assert refreshed.worker_id == "worker-1"


@pytest.mark.asyncio
async def test_operation_worker_returns_claimed_operation_to_retry_on_cancellation(
    operation_service, tenant
) -> None:
    operation = await operation_service.enqueue(
        tenant.id, "blocking", "worker-lifecycle:cancel", {}
    )
    started = asyncio.Event()

    async def blocking(_operation):
        started.set()
        await asyncio.Event().wait()

    worker = OperationWorker(operation_service.session, handlers={"blocking": blocking})
    task = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    refreshed = await operation_service.get(tenant.id, operation.id)
    assert refreshed is not None
    assert refreshed.status == OperationStatus.RETRY_WAIT
    assert refreshed.error_code == "worker_shutdown"
    assert refreshed.lease_expires_at is None


@pytest.mark.asyncio
async def test_operation_worker_marks_webhook_failed_and_leaves_it_retryable(
    operation_service, tenant, monkeypatch
) -> None:
    connection = WeChatConnection(
        tenant_id=tenant.id,
        capability=Capability.LOCAL_LIFE.value,
        mode=ConnectionMode.MOCK.value,
    )
    operation_service.session.add(connection)
    await operation_service.session.flush()
    event = WebhookEvent(
        tenant_id=tenant.id,
        connection_id=connection.id,
        fingerprint="l" * 64,
        event_type="product_audit",
        payload={"product_id": "p-1"},
    )
    operation_service.session.add(event)
    await operation_service.session.commit()

    async def fail_handler(session, callback):
        del session, callback
        raise RuntimeError("callback failed")

    monkeypatch.setattr("poi_admin.operations.worker.process_webhook_event", fail_handler)
    worker = OperationWorker(operation_service.session, handlers={})
    assert await worker.run_once() is None

    refreshed = (
        await operation_service.session.execute(
            select(WebhookEvent).where(WebhookEvent.id == event.id)
        )
    ).scalar_one()
    assert refreshed.status == "retry_wait"
    assert refreshed.attempt_count == 1
    assert refreshed.error_message == "Webhook processing failed; inspect server logs"


@pytest.mark.asyncio
async def test_failed_webhook_does_not_starve_operation_queue(
    operation_service, tenant, monkeypatch
) -> None:
    connection = WeChatConnection(
        tenant_id=tenant.id,
        capability=Capability.LOCAL_LIFE.value,
        mode=ConnectionMode.MOCK.value,
    )
    operation_service.session.add(connection)
    await operation_service.session.flush()
    operation_service.session.add(
        WebhookEvent(
            tenant_id=tenant.id,
            connection_id=connection.id,
            fingerprint="s" * 64,
            event_type="poison",
            payload={},
        )
    )
    operation = await operation_service.enqueue(tenant.id, "sync", "no-starvation", {})

    async def fail_webhook(session, callback):
        del session, callback
        raise RuntimeError("private callback failure")

    async def handle_operation(_operation):
        return {"ok": True}

    monkeypatch.setattr("poi_admin.operations.worker.process_webhook_event", fail_webhook)
    worker = OperationWorker(
        operation_service.session, handlers={"sync": handle_operation}
    )
    assert await worker.run_once() is None
    completed = await worker.run_once()

    assert completed is not None and completed.id == operation.id
    refreshed = await operation_service.get(tenant.id, operation.id)
    assert refreshed is not None and refreshed.status == OperationStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_webhook_moves_to_dead_letter_after_attempt_budget(
    operation_service, tenant, monkeypatch
) -> None:
    connection = WeChatConnection(
        tenant_id=tenant.id,
        capability=Capability.LOCAL_LIFE.value,
        mode=ConnectionMode.MOCK.value,
    )
    operation_service.session.add(connection)
    await operation_service.session.flush()
    event = WebhookEvent(
        tenant_id=tenant.id,
        connection_id=connection.id,
        fingerprint="d" * 64,
        event_type="poison",
        payload={},
        max_attempts=1,
    )
    operation_service.session.add(event)
    await operation_service.session.commit()

    async def fail_webhook(session, callback):
        del session, callback
        raise RuntimeError("private callback failure")

    monkeypatch.setattr("poi_admin.operations.worker.process_webhook_event", fail_webhook)
    await OperationWorker(operation_service.session, handlers={}).run_once()
    await operation_service.session.refresh(event)

    assert event.status == "dead_letter"
    assert event.attempt_count == 1
