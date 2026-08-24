from __future__ import annotations

import pytest
from sqlalchemy import func, select

from poi_admin.audit.models import AuditLog
from poi_admin.audit.service import AuditService
from poi_admin.connections.models import WeChatConnection
from poi_admin.identity.models import Tenant
from poi_admin.local_life.models import (
    FundsFlow,
    LocalOrder,
    LocalProduct,
    LocalVoucher,
    VoucherBill,
)
from poi_admin.seed import seed_demo
from poi_admin.stores.models import ServicePoi, Store, StorePoiMapping


@pytest.mark.asyncio
async def test_audit_log_redacts_secrets_and_is_append_only(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one()
        row = await AuditService(session).record(
            tenant_id=tenant.id,
            actor_user_id=None,
            action="connection.updated",
            resource_type="connection",
            resource_id="c1",
            before={"access_token": "secret-value"},
            after={"voucher_code": "123456"},
        )
        assert row.before_summary == {"access_token": "[REDACTED]"}
        assert row.after_summary == {"voucher_code": "[REDACTED]"}
        assert await AuditService(session).list_for_tenant(tenant.id)


@pytest.mark.asyncio
async def test_seed_demo_is_idempotent(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        first = await seed_demo(session)
        second = await seed_demo(session)
        assert first == second
        assert len((await session.execute(select(AuditLog))).scalars().all()) == 0


@pytest.mark.asyncio
async def test_seed_demo_populates_the_operational_workflow(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        await seed_demo(session)
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one()

        async def count(model, *criteria) -> int:
            value = await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.tenant_id == tenant.id, *criteria)
            )
            return int(value or 0)

        assert await count(WeChatConnection) == 2
        assert await count(Store) >= 1
        assert await count(ServicePoi) >= 1
        assert await count(StorePoiMapping, StorePoiMapping.state == "active") >= 1
        assert await count(LocalProduct) >= 1
        assert await count(LocalOrder) >= 1
        assert await count(LocalVoucher, LocalVoucher.state == "available") >= 1
        assert await count(FundsFlow) >= 1
        assert await count(VoucherBill) >= 1
