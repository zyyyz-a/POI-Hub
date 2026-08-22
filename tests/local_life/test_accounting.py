from __future__ import annotations

import pytest
from sqlalchemy import select

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.identity.models import Tenant
from poi_admin.local_life.accounting import AccountingService
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
        operation = await service.sync_accounting(tenant.id, connection.id, "accounting-1")
        assert operation.status == OperationStatus.QUEUED.value
        result = await service.reconciliation_summary(tenant.id)
        assert result["fund_count"] == 0
        assert result["bill_count"] == 0
