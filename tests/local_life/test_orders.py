from __future__ import annotations

import pytest
from sqlalchemy import select

from poi_admin.connections.mock import MockLocalLifeGateway
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.identity.models import Tenant
from poi_admin.local_life.models import LocalOrder
from poi_admin.local_life.orders import OrderService, order_operation_handlers
from poi_admin.local_life.schemas import OrderSyncRequest
from poi_admin.operations.models import OperationStatus


@pytest.mark.asyncio
async def test_order_sync_persists_seeded_order_and_is_tenant_scoped(client) -> None:
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
        service = OrderService(session)
        request = OrderSyncRequest(
            connection_id=connection.id,
            external_order_id="mock-order-seeded",
            idempotency_key="order-sync-1",
        )
        order, operation = await service.sync_order(tenant.id, request)
        duplicate_order, duplicate_operation = await service.sync_order(tenant.id, request)
        assert order.id == duplicate_order.id
        assert operation.id == duplicate_operation.id
        assert order.external_order_id == "mock-order-seeded"

        handlers = order_operation_handlers(
            session, gateway_override=MockLocalLifeGateway(tenant.id)
        )
        result = await handlers["local_life.order.sync"](operation)
        assert result["order_id"] == order.id
        refreshed = await session.get(LocalOrder, order.id)
        assert refreshed is not None
        assert refreshed.status == "paid"

        other = Tenant(name="Other order tenant", slug="other-order-tenant")
        session.add(other)
        await session.commit()
        assert await service.list_orders(other.id) == []


@pytest.mark.asyncio
async def test_after_sale_sync_is_durable_and_accepted(client) -> None:
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
        service = OrderService(session)
        order, _ = await service.sync_order(
            tenant.id,
            OrderSyncRequest(
                connection_id=connection.id,
                external_order_id="mock-order-after-sale",
                idempotency_key="order-sync-after-sale",
            ),
        )
        accepted = await service.sync_after_sale(
            tenant.id, order.id, "after-sale-1", "after-sale-sync-1"
        )
        assert accepted.status == OperationStatus.QUEUED.value
        assert accepted.command_type == "local_life.after_sale.sync"
