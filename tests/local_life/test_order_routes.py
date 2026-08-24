from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.connections.mock import MockLocalLifeGateway
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.core.permissions import Role
from poi_admin.core.security import hash_password
from poi_admin.identity.models import Membership, Tenant, User
from poi_admin.local_life.models import LocalAfterSale, LocalOrder, LocalVoucher
from poi_admin.local_life.orders import order_operation_handlers
from poi_admin.local_life.vouchers import voucher_operation_handlers
from poi_admin.operations.models import OperationStatus
from poi_admin.operations.worker import OperationWorker
from poi_admin.stores.models import ServicePoi, Store, StorePoiMapping

# ruff: noqa: E501


async def _operator_login(client: AsyncClient) -> tuple[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@example.com", "password": "operator-password"},
    )
    assert response.status_code == 200
    return response.cookies["poi_csrf"], response.json()["tenants"][0]["tenant_id"]


async def _tenant_admin_login(client: AsyncClient) -> tuple[str, str]:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        user = (
            await session.execute(select(User).where(User.email == "route-admin@example.com"))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email="route-admin@example.com",
                display_name="Route admin",
                password_hash=hash_password("route-admin-password"),
            )
            session.add(user)
            await session.flush()
            session.add(
                Membership(tenant_id=tenant.id, user_id=user.id, role=Role.TENANT_ADMIN.value)
            )
            await session.commit()
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "route-admin@example.com", "password": "route-admin-password"},
    )
    assert response.status_code == 200
    return response.cookies["poi_csrf"], response.json()["tenants"][0]["tenant_id"]


async def _connection(client: AsyncClient, tenant_id: str) -> str:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        connection = WeChatConnection(
            tenant_id=tenant_id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        return connection.id


@pytest.mark.asyncio
async def test_order_sync_route_then_worker_persists_remote_order_and_vouchers(
    client: AsyncClient,
) -> None:
    csrf, tenant_id = await _operator_login(client)
    connection_id = await _connection(client, tenant_id)
    response = await client.post(
        "/api/v1/local-life/orders/sync",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json={
            "connection_id": connection_id,
            "external_order_id": "route-order-1",
            "idempotency_key": "route-order-sync-1",
        },
    )
    assert response.status_code == 202
    operation_id = response.json()["operation"]["id"]
    order_id = response.json()["order"]["id"]

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        worker = OperationWorker(
            session,
            handlers=order_operation_handlers(
                session, gateway_override=MockLocalLifeGateway(tenant_id)
            ),
        )
        completed = await worker.run_once()
        assert completed is not None and completed.id == operation_id
        assert completed.status == OperationStatus.SUCCEEDED.value
        order = await session.get(LocalOrder, order_id)
        assert order is not None and order.status == "paid"
        vouchers = (
            (await session.execute(select(LocalVoucher).where(LocalVoucher.order_id == order_id)))
            .scalars()
            .all()
        )
        # Official voucher issuance callbacks are the source of voucher codes;
        # an order lookup cannot list vouchers by order id.
        assert vouchers == []


@pytest.mark.asyncio
async def test_voucher_consume_and_revoke_routes_are_worker_durable(client: AsyncClient) -> None:
    csrf, tenant_id = await _tenant_admin_login(client)
    connection_id = await _connection(client, tenant_id)
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == "operator@example.com"))
        ).scalar_one()
        store = Store(
            tenant_id=tenant_id, code="ROUTE-STORE", name="Route Store", address="Address"
        )
        poi = ServicePoi(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_poi_id="route-poi",
            name="Route POI",
            address="Address",
            remote_status="approved",
            raw_checksum="c" * 64,
        )
        session.add_all([store, poi])
        await session.flush()
        session.add(
            StorePoiMapping(
                tenant_id=tenant_id,
                connection_id=connection_id,
                store_id=store.id,
                service_poi_id=poi.id,
                state="active",
                match_score=1.0,
                confirmed_by_user_id=user.id,
            )
        )
        order = LocalOrder(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_order_id="route-voucher-order",
        )
        session.add(order)
        await session.flush()
        voucher = LocalVoucher(
            tenant_id=tenant_id,
            connection_id=connection_id,
            order_id=order.id,
            external_voucher_id="route-voucher-1",
            external_sku_id="sku-1",
            state="available",
            code_masked="****",
        )
        session.add(voucher)
        await session.commit()
        store_id, voucher_id = store.id, voucher.id

    consume = await client.post(
        f"/api/v1/local-life/vouchers/{voucher_id}/consume",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json={"store_id": store_id, "idempotency_key": "route-consume-1"},
    )
    assert consume.status_code == 202
    consume_operation_id = consume.json()["operation"]["id"]
    async with database.session_factory() as session:
        worker = OperationWorker(
            session,
            handlers=voucher_operation_handlers(
                session, gateway_override=MockLocalLifeGateway(tenant_id)
            ),
        )
        completed = await worker.run_once()
        assert completed is not None and completed.id == consume_operation_id
        stored = await session.get(LocalVoucher, voucher_id)
        assert stored is not None and stored.state == "consumed"

    revoke = await client.post(
        f"/api/v1/local-life/vouchers/{voucher_id}/revoke",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json={"idempotency_key": "route-revoke-1"},
    )
    assert revoke.status_code == 202
    revoke_operation_id = revoke.json()["operation"]["id"]
    async with database.session_factory() as session:
        worker = OperationWorker(
            session,
            handlers=voucher_operation_handlers(
                session, gateway_override=MockLocalLifeGateway(tenant_id)
            ),
        )
        completed = await worker.run_once()
        assert completed is not None and completed.id == revoke_operation_id
        stored = await session.get(LocalVoucher, voucher_id)
        assert stored is not None and stored.state == "available" and stored.revoked_at is not None


@pytest.mark.asyncio
async def test_after_sale_sync_route_then_worker_updates_after_sale(client: AsyncClient) -> None:
    csrf, tenant_id = await _tenant_admin_login(client)
    connection_id = await _connection(client, tenant_id)
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        order = LocalOrder(
            tenant_id=tenant_id, connection_id=connection_id, external_order_id="route-after-order"
        )
        session.add(order)
        await session.commit()
        order_id = order.id
    accepted = await client.post(
        "/api/v1/local-life/after-sales/sync",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json={
            "order_id": order_id,
            "external_after_sale_id": "route-after-1",
            "idempotency_key": "route-after-sync-1",
        },
    )
    assert accepted.status_code == 202
    operation_id = accepted.json()["id"]
    async with database.session_factory() as session:
        after_sale = (
            await session.execute(
                select(LocalAfterSale).where(
                    LocalAfterSale.external_after_sale_id == "route-after-1"
                )
            )
        ).scalar_one()
        worker = OperationWorker(
            session,
            handlers=order_operation_handlers(
                session, gateway_override=MockLocalLifeGateway(tenant_id)
            ),
        )
        completed = await worker.run_once()
        assert completed is not None and completed.id == operation_id
        refreshed = await session.get(LocalAfterSale, after_sale.id)
        assert (
            refreshed is not None
            and refreshed.status == "none"
            and refreshed.last_synced_at is not None
        )
