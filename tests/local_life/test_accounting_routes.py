from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.connections.mock import MockLocalLifeGateway
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.identity.models import Tenant
from poi_admin.local_life.accounting import accounting_operation_handlers
from poi_admin.local_life.models import FundsFlow, VoucherBill
from poi_admin.operations.models import OperationStatus
from poi_admin.operations.worker import OperationWorker

# ruff: noqa: E501


async def _login(client: AsyncClient) -> tuple[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@example.com", "password": "operator-password"},
    )
    assert response.status_code == 200
    return response.cookies["poi_csrf"], response.json()["tenants"][0]["tenant_id"]


@pytest.mark.asyncio
async def test_accounting_sync_route_then_worker_persists_entries_and_reconciliation(
    client: AsyncClient,
) -> None:
    csrf, tenant_id = await _login(client)
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        connection = WeChatConnection(
            tenant_id=tenant_id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        connection_id = connection.id

    initial = await client.get(
        "/api/v1/local-life/accounting/reconciliation",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert initial.status_code == 200
    assert initial.json()["fund_count"] == initial.json()["bill_count"] == 0

    accepted = await client.post(
        "/api/v1/local-life/accounting/sync",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json={
            "connection_id": connection_id,
            "product_id": "product-1",
            "bill_date": "2026-08-24",
            "idempotency_key": "account-route-sync-1",
        },
    )
    assert accepted.status_code == 202
    operation_id = accepted.json()["operation"]["id"]
    assert accepted.json()["summary"]["fund_count"] == 0

    async with database.session_factory() as session:
        worker = OperationWorker(
            session,
            handlers=accounting_operation_handlers(
                session, gateway_override=MockLocalLifeGateway(tenant_id)
            ),
        )
        completed = await worker.run_once()
        assert completed is not None and completed.id == operation_id
        assert completed.status == OperationStatus.SUCCEEDED.value
        funds = (
            (await session.execute(select(FundsFlow).where(FundsFlow.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        bills = (
            (await session.execute(select(VoucherBill).where(VoucherBill.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        assert len(funds) == len(bills) == 1
        assert funds[0].amount == bills[0].amount == 9900

    funds_response = await client.get(
        "/api/v1/local-life/funds", headers={"X-Tenant-ID": tenant_id}
    )
    bills_response = await client.get(
        "/api/v1/local-life/bills", headers={"X-Tenant-ID": tenant_id}
    )
    reconciliation = await client.get(
        "/api/v1/local-life/accounting/reconciliation", headers={"X-Tenant-ID": tenant_id}
    )
    assert (
        funds_response.status_code
        == bills_response.status_code
        == reconciliation.status_code
        == 200
    )
    assert funds_response.json()[0]["amount"] == bills_response.json()[0]["amount"] == 9900
    assert reconciliation.json()["fund_count"] == reconciliation.json()["bill_count"] == 1
    assert reconciliation.json()["difference"] == 0
    assert reconciliation.json()["difference_count"] == 0


@pytest.mark.asyncio
async def test_accounting_routes_are_tenant_isolated(client: AsyncClient) -> None:
    _, tenant_id = await _login(client)
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        other = Tenant(name="Accounting Other", slug="accounting-other")
        session.add(other)
        await session.commit()
        other_id = other.id
    response = await client.get(
        "/api/v1/local-life/accounting/reconciliation",
        headers={"X-Tenant-ID": other_id},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "tenant_access_denied"
