from __future__ import annotations

import pytest
from sqlalchemy import select

from poi_admin.connections.mock import MockLocalLifeGateway
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.identity.models import Tenant
from poi_admin.local_life.accounting import AccountingService, accounting_operation_handlers
from poi_admin.operations.models import OperationStatus


@pytest.mark.asyncio
async def test_accounting_sync_is_durable_and_reports_bill_differences(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        service = AccountingService(session)
        operation = await service.sync_accounting(
            tenant.id, connection.id, "product-1", "2026-08-24", "accounting-1"
        )
        assert operation.status == OperationStatus.QUEUED.value
        result = await service.reconciliation_summary(tenant.id)
        assert result["fund_count"] == 0
        assert result["bill_count"] == 0


@pytest.mark.asyncio
async def test_accounting_worker_reads_every_remote_page(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        operation = await AccountingService(session).sync_accounting(
            tenant.id, connection.id, "product-1", "2026-08-24", "accounting-pages"
        )

        class PagedGateway(MockLocalLifeGateway):
            async def list_funds(self, cursor=None):
                if cursor is None:
                    return ([{"id": "fund-1", "amount": 100}], "fund-next")
                return ([{"id": "fund-2", "amount": 200}], None)

            async def list_bills(self, product_id, bill_date, cursor=None):
                del product_id, bill_date
                if cursor is None:
                    return ([{"id": "bill-1", "amount": 100}], "bill-next")
                return ([{"id": "bill-2", "amount": 200}], None)

        result = await accounting_operation_handlers(
            session, gateway_override=PagedGateway(tenant.id)
        )["local_life.accounting.sync"](operation)

        assert result["fund_count"] == 2
        assert result["bill_count"] == 2
