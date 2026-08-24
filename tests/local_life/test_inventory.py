from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from poi_admin.connections.mock import MockLocalLifeGateway
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.identity.models import Tenant
from poi_admin.local_life.models import LocalProduct, LocalSku, ProductStatus
from poi_admin.local_life.products import ProductService
from poi_admin.local_life.schemas import StockUpdateRequest


async def _seed_remote_product(client: AsyncClient) -> tuple[str, str, str]:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.flush()
        gateway = MockLocalLifeGateway(tenant.id)
        remote = await gateway.create_product(
            {
                "merchant_product_id": "STOCK-001",
                "name": "库存测试商品",
                "skus": [
                    {
                        "merchant_sku_id": "STOCK-SKU-1",
                        "name": "标准套餐",
                        "sale_price": 1000,
                    }
                ],
            }
        )
        product = LocalProduct(
            tenant_id=tenant.id,
            connection_id=connection.id,
            merchant_product_id="STOCK-001",
            external_product_id=remote.external_id,
            name="库存测试商品",
            remote_status="approved",
            desired_state="approved",
        )
        session.add(product)
        await session.flush()
        sku = LocalSku(
            tenant_id=tenant.id,
            product_id=product.id,
            merchant_sku_id="STOCK-SKU-1",
            external_sku_id=remote.skus[0].external_id,
            name="标准套餐",
            sale_price=1000,
            market_price=1500,
            stock=5,
            desired_stock=5,
        )
        session.add(sku)
        await session.commit()
        return tenant.id, product.id, sku.id


def test_stock_request_rejects_negative_values() -> None:
    with pytest.raises(ValueError):
        StockUpdateRequest(stock=-1, version=1, idempotency_key="stock-negative")


@pytest.mark.asyncio
async def test_stock_update_is_durable_idempotent_and_applied_by_worker(
    client: AsyncClient,
) -> None:
    tenant_id, product_id, sku_id = await _seed_remote_product(client)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@example.com", "password": "operator-password"},
    )
    headers = {
        "X-Tenant-ID": tenant_id,
        "X-CSRF-Token": login.json()["csrf_token"],
    }
    payload = {"stock": 18, "version": 1, "idempotency_key": "stock-18-v1"}

    accepted = await client.put(
        f"/api/v1/local-life/skus/{sku_id}/stock", headers=headers, json=payload
    )
    duplicate = await client.put(
        f"/api/v1/local-life/skus/{sku_id}/stock", headers=headers, json=payload
    )

    assert accepted.status_code == 202
    assert duplicate.json()["operation_id"] == accepted.json()["operation_id"]
    assert accepted.json()["sku"]["product_id"] == product_id
    assert accepted.json()["sku"]["stock"] == 5
    assert accepted.json()["sku"]["desired_stock"] == 18

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    settings = client._transport.app.state.settings  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        operation = await ProductService(session, settings=settings).run_next_operation()
        assert operation is not None
        assert operation.status == "succeeded"

    detail = await client.get(
        f"/api/v1/local-life/products/{product_id}", headers={"X-Tenant-ID": tenant_id}
    )
    assert detail.status_code == 200
    assert detail.json()["skus"][0]["stock"] == 18
    assert detail.json()["skus"][0]["version"] == 2


@pytest.mark.asyncio
async def test_stock_update_is_tenant_scoped(client: AsyncClient) -> None:
    tenant_id, _, sku_id = await _seed_remote_product(client)
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        other = Tenant(name="库存其他租户", slug="stock-other")
        session.add(other)
        await session.commit()
        request = StockUpdateRequest(stock=9, version=1, idempotency_key="other-stock")
        with pytest.raises(Exception) as failure:
            await ProductService(session).update_stock(other.id, sku_id, request)
        assert getattr(failure.value, "code", None) == "sku_not_found"
        assert tenant_id != other.id


@pytest.mark.asyncio
async def test_deleted_product_rejects_stock_update(client: AsyncClient) -> None:
    tenant_id, product_id, sku_id = await _seed_remote_product(client)
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        product = await ProductService(session).get_product(tenant_id, product_id)
        assert product is not None
        product.remote_status = ProductStatus.DELETED.value
        await session.commit()

        request = StockUpdateRequest(
            stock=9, version=1, idempotency_key="deleted-product-stock"
        )
        with pytest.raises(Exception) as failure:
            await ProductService(session).update_stock(tenant_id, sku_id, request)

        assert getattr(failure.value, "code", None) == "invalid_product_transition"
