from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.identity.models import Tenant
from poi_admin.operations.service import OperationService


@pytest.mark.asyncio
async def test_batch_retry_endpoint_is_tenant_scoped_and_reports_partial_results(
    client: AsyncClient,
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    csrf = login.json()["csrf_token"]
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        service = OperationService(session)
        failed = await service.enqueue(tenant.id, "sync", "route-batch-failed", {})
        claimed = await service.claim("worker-route")
        assert claimed is not None
        await service.mark_failed(claimed, code="terminal", message="failed", retryable=False)
        queued = await service.enqueue(tenant.id, "sync", "route-batch-queued", {})

    selected = await client.post(
        "/api/v1/auth/select-tenant",
        headers={"X-CSRF-Token": csrf},
        json={"tenant_id": tenant.id},
    )
    assert selected.status_code == 200
    response = await client.post(
        "/api/v1/operations/retry-batch",
        headers={"X-CSRF-Token": csrf},
        json={"operation_ids": [failed.id, queued.id, "missing"]},
    )

    assert response.status_code == 200
    assert response.json()["accepted_count"] == 1
    assert response.json()["rejected_count"] == 2
    assert response.headers["X-Request-ID"]
