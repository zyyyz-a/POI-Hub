"""Deterministic local demo bootstrap; safe to run repeatedly."""

from __future__ import annotations

import argparse
import asyncio
import hashlib

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Import every model module before metadata-based reset/create operations.
from poi_admin.audit import models as _audit_models  # noqa: F401,E402
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.core.config import Settings, get_settings
from poi_admin.core.database import create_database
from poi_admin.identity.models import Tenant, User
from poi_admin.identity.service import ensure_test_identity
from poi_admin.local_life.models import (
    FundsFlow,
    LocalOrder,
    LocalProduct,
    LocalSku,
    LocalVoucher,
    VoucherBill,
)
from poi_admin.operations import models as _operation_models  # noqa: F401,E402
from poi_admin.stores.models import ServicePoi, Store, StorePoiMapping
from poi_admin.webhooks import models as _webhook_models  # noqa: F401,E402


async def seed_demo(session: AsyncSession) -> dict[str, int]:
    await ensure_test_identity(session)
    tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
    admin = (
        await session.execute(select(User).where(User.email == "admin@example.com"))
    ).scalar_one()
    connections = 0
    for capability in (Capability.LOCAL_LIFE.value, Capability.SERVICE_POI.value):
        existing = (
            await session.execute(
                select(WeChatConnection).where(
                    WeChatConnection.tenant_id == tenant.id,
                    WeChatConnection.capability == capability,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                WeChatConnection(
                    tenant_id=tenant.id,
                    capability=capability,
                    mode=ConnectionMode.MOCK.value,
                    status="authorized",
                )
            )
            connections += 1
    await session.commit()

    local_connection = (
        await session.execute(
            select(WeChatConnection).where(
                WeChatConnection.tenant_id == tenant.id,
                WeChatConnection.capability == Capability.LOCAL_LIFE.value,
            )
        )
    ).scalar_one()
    poi_connection = (
        await session.execute(
            select(WeChatConnection).where(
                WeChatConnection.tenant_id == tenant.id,
                WeChatConnection.capability == Capability.SERVICE_POI.value,
            )
        )
    ).scalar_one()

    store = (
        await session.execute(
            select(Store).where(Store.tenant_id == tenant.id, Store.code == "DEMO-001")
        )
    ).scalar_one_or_none()
    if store is None:
        store = Store(
            tenant_id=tenant.id,
            code="DEMO-001",
            name="西湖演示门店",
            city="杭州市",
            district="西湖区",
            address="孤山路 1 号",
            latitude=30.2501,
            longitude=120.1601,
            status="active",
        )
        session.add(store)
        await session.flush()

    poi = (
        await session.execute(
            select(ServicePoi).where(
                ServicePoi.tenant_id == tenant.id,
                ServicePoi.connection_id == poi_connection.id,
                ServicePoi.external_poi_id == "seed-poi-1",
            )
        )
    ).scalar_one_or_none()
    if poi is None:
        poi = ServicePoi(
            tenant_id=tenant.id,
            connection_id=poi_connection.id,
            external_poi_id="seed-poi-1",
            name="西湖演示门店",
            address="杭州市西湖区孤山路 1 号",
            latitude=30.2501,
            longitude=120.1601,
            remote_status="approved",
            raw_checksum=hashlib.sha256(b"seed-poi-1").hexdigest(),
        )
        session.add(poi)
        await session.flush()
    mapping = (
        await session.execute(
            select(StorePoiMapping).where(
                StorePoiMapping.tenant_id == tenant.id,
                StorePoiMapping.connection_id == poi_connection.id,
                StorePoiMapping.store_id == store.id,
                StorePoiMapping.service_poi_id == poi.id,
                StorePoiMapping.state == "active",
            )
        )
    ).scalar_one_or_none()
    if mapping is None:
        session.add(
            StorePoiMapping(
                tenant_id=tenant.id,
                connection_id=poi_connection.id,
                store_id=store.id,
                service_poi_id=poi.id,
                state="active",
                match_score=1.0,
                match_evidence={"source": "seed", "reason": "deterministic demo mapping"},
                confirmed_by_user_id=admin.id,
            )
        )

    product = (
        await session.execute(
            select(LocalProduct).where(
                LocalProduct.tenant_id == tenant.id,
                LocalProduct.connection_id == local_connection.id,
                LocalProduct.merchant_product_id == "DEMO-PRODUCT-001",
            )
        )
    ).scalar_one_or_none()
    if product is None:
        product = LocalProduct(
            tenant_id=tenant.id,
            connection_id=local_connection.id,
            external_product_id="seed-product-1",
            merchant_product_id="DEMO-PRODUCT-001",
            name="西湖双人套餐",
            head_images=["https://example.com/demo-product.jpg"],
            remote_status="listed",
            desired_state="listed",
            verification_settings={"valid_days": 30},
            rules={"demo": True},
        )
        session.add(product)
        await session.flush()
    sku = (
        await session.execute(
            select(LocalSku).where(
                LocalSku.tenant_id == tenant.id,
                LocalSku.product_id == product.id,
                LocalSku.merchant_sku_id == "DEMO-SKU-001",
            )
        )
    ).scalar_one_or_none()
    if sku is None:
        session.add(
            LocalSku(
                tenant_id=tenant.id,
                product_id=product.id,
                external_sku_id="seed-sku-1",
                merchant_sku_id="DEMO-SKU-001",
                name="双人套餐",
                sale_price=9900,
                market_price=12900,
                stock=30,
                desired_stock=20,
            )
        )

    order = (
        await session.execute(
            select(LocalOrder).where(
                LocalOrder.tenant_id == tenant.id,
                LocalOrder.connection_id == local_connection.id,
                LocalOrder.external_order_id == "seed-order-1",
            )
        )
    ).scalar_one_or_none()
    if order is None:
        order = LocalOrder(
            tenant_id=tenant.id,
            connection_id=local_connection.id,
            external_order_id="seed-order-1",
            status="paid",
            total_amount=9900,
            paid_amount=9900,
            customer_reference_masked="****1001",
            raw_summary={"status": "paid", "total_amount": 9900},
        )
        session.add(order)
        await session.flush()
    voucher = (
        await session.execute(
            select(LocalVoucher).where(
                LocalVoucher.tenant_id == tenant.id,
                LocalVoucher.connection_id == local_connection.id,
                LocalVoucher.external_voucher_id == "seed-voucher-1",
            )
        )
    ).scalar_one_or_none()
    if voucher is None:
        session.add(
            LocalVoucher(
                tenant_id=tenant.id,
                connection_id=local_connection.id,
                order_id=order.id,
                external_voucher_id="seed-voucher-1",
                external_product_id=product.external_product_id,
                external_sku_id="seed-sku-1",
                code_masked="******0001",
                state="available",
                raw_summary={"state": "available"},
            )
        )

    fund = (
        await session.execute(
            select(FundsFlow).where(
                FundsFlow.tenant_id == tenant.id,
                FundsFlow.connection_id == local_connection.id,
                FundsFlow.external_entry_id == "seed-fund-1",
            )
        )
    ).scalar_one_or_none()
    if fund is None:
        session.add(
            FundsFlow(
                tenant_id=tenant.id,
                connection_id=local_connection.id,
                external_entry_id="seed-fund-1",
                entry_type="order_payment",
                amount=9900,
                currency="CNY",
                raw_summary={"amount": 9900, "currency": "CNY"},
            )
        )
    bill = (
        await session.execute(
            select(VoucherBill).where(
                VoucherBill.tenant_id == tenant.id,
                VoucherBill.connection_id == local_connection.id,
                VoucherBill.external_bill_id == "seed-bill-1",
            )
        )
    ).scalar_one_or_none()
    if bill is None:
        session.add(
            VoucherBill(
                tenant_id=tenant.id,
                connection_id=local_connection.id,
                external_bill_id="seed-bill-1",
                bill_type="order_payment",
                amount=9900,
                currency="CNY",
                raw_summary={"amount": 9900, "currency": "CNY"},
            )
        )
    await session.commit()
    total_connections = await session.scalar(
        select(func.count())
        .select_from(WeChatConnection)
        .where(WeChatConnection.tenant_id == tenant.id)
    )
    return {"tenants": 1, "connections_created": int(total_connections or 0)}


async def reset_and_seed(
    settings: Settings | None = None, *, reset: bool = False
) -> dict[str, int]:
    database = create_database(settings or get_settings())
    try:
        if reset:
            async with database.engine.begin() as connection:
                from poi_admin.core.orm import Base

                await connection.run_sync(Base.metadata.drop_all)
                await connection.run_sync(Base.metadata.create_all)
                await connection.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS alembic_version "
                        "(version_num VARCHAR(32) NOT NULL)"
                    )
                )
                await connection.execute(text("DELETE FROM alembic_version"))
                await connection.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES ('0008_audit')")
                )
        async with database.session_factory() as session:
            return await seed_demo(session)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    print(asyncio.run(reset_and_seed(reset=args.reset)))


if __name__ == "__main__":
    main()


__all__ = ["main", "reset_and_seed", "seed_demo"]
