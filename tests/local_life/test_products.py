from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.core.permissions import Role
from poi_admin.core.security import hash_password
from poi_admin.identity.models import Membership, Tenant, User
from poi_admin.local_life.models import LocalProduct
from poi_admin.local_life.products import ProductService
from poi_admin.local_life.schemas import ProductCreateRequest, ProductUpdateRequest
from poi_admin.operations.models import IntegrationOperation, OperationStatus
from poi_admin.operations.worker import OperationWorker


def valid_product_payload(connection_id: str = "connection-1") -> dict[str, object]:
    return {
        "connection_id": connection_id,
        "idempotency_key": "create-breakfast-v1",
        "merchant_product_id": "BREAKFAST-001",
        "name": "双人早餐团购",
        "product_type": "group_buying",
        "category": "餐饮",
        "brand": "西湖餐厅",
        "head_images": ["https://example.test/breakfast.jpg"],
        "available_store_desc": "西湖门店可用",
        "rules": {"refund_policy": "unused_refundable"},
        "skus": [
            {
                "merchant_sku_id": "BREAKFAST-001-2P",
                "name": "双人套餐",
                "sale_price": 8800,
                "market_price": 12800,
                "stock": 25,
            }
        ],
    }


def test_product_request_rejects_invalid_prices_and_blank_names() -> None:
    payload = valid_product_payload()
    payload["name"] = "   "
    with pytest.raises(ValidationError):
        ProductCreateRequest.model_validate(payload)

    payload = valid_product_payload()
    payload["skus"] = [
        {
            "merchant_sku_id": "OVERPRICED",
            "name": "无效套餐",
            "sale_price": 12900,
            "market_price": 12800,
            "stock": 1,
        }
    ]
    with pytest.raises(ValidationError):
        ProductCreateRequest.model_validate(payload)


def test_product_update_requires_at_least_one_valid_change() -> None:
    with pytest.raises(ValidationError):
        ProductUpdateRequest(version=1, idempotency_key="empty-update")
    with pytest.raises(ValidationError):
        ProductUpdateRequest(
            version=1,
            idempotency_key="blank-name-update",
            name="   ",
        )

@pytest.mark.asyncio
async def test_create_is_tenant_scoped_and_idempotent(client: AsyncClient) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as tenant_session:
        tenant_id = (
            await tenant_session.execute(select(Tenant.id).where(Tenant.slug == "demo"))
        ).scalar_one()
    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    admin_headers = {
        "X-Tenant-ID": tenant_id,
        "X-CSRF-Token": admin_login.json()["csrf_token"],
    }
    connection = await client.post(
        "/api/v1/connections",
        headers=admin_headers,
        json={"capability": "local_life", "mode": "mock"},
    )
    assert connection.status_code == 201

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@example.com", "password": "operator-password"},
    )
    headers = {
        "X-Tenant-ID": tenant_id,
        "X-CSRF-Token": login.json()["csrf_token"],
    }
    payload = valid_product_payload(connection.json()["id"])

    created = await client.post("/api/v1/local-life/products", headers=headers, json=payload)
    duplicate = await client.post("/api/v1/local-life/products", headers=headers, json=payload)

    assert created.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json()["operation_id"] == created.json()["operation_id"]
    assert duplicate.json()["product"]["id"] == created.json()["product"]["id"]
    assert created.json()["product"]["remote_status"] == "pending_create"
    assert created.json()["product"]["skus"][0]["stock"] == 0
    assert created.json()["product"]["skus"][0]["desired_stock"] == 25

    listed = await client.get(
        "/api/v1/local-life/products", headers={"X-Tenant-ID": tenant_id}
    )
    assert listed.status_code == 200
    assert [item["merchant_product_id"] for item in listed.json()] == ["BREAKFAST-001"]

    settings = client._transport.app.state.settings  # type: ignore[attr-defined]
    async with database.session_factory() as worker_session:
        worker = OperationWorker(worker_session, settings=settings)
        create_operation = await worker.run_once()
        stock_operation = await worker.run_once()
        assert create_operation is not None
        assert create_operation.command_type == "local_life.product.create"
        assert create_operation.status == "succeeded"
        assert stock_operation is not None
        assert stock_operation.command_type == "local_life.inventory.set"
        assert stock_operation.status == "succeeded"

    synchronized = await client.get(
        f"/api/v1/local-life/products/{created.json()['product']['id']}",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert synchronized.json()["external_product_id"] is not None
    assert synchronized.json()["skus"][0]["stock"] == 25

    async with database.session_factory() as session:
        other_tenant = Tenant(name="另一租户", slug="local-life-other")
        session.add(other_tenant)
        await session.commit()
        service = ProductService(session)
        assert await service.list_products(other_tenant.id) == []
        assert (
            await service.get_product(other_tenant.id, created.json()["product"]["id"])
            is None
        )


@pytest.mark.asyncio
async def test_create_rejects_non_local_life_connection(client: AsyncClient) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.SERVICE_POI.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()

        request = ProductCreateRequest.model_validate(valid_product_payload(connection.id))
        with pytest.raises(Exception) as failure:
            await ProductService(session).create_product(tenant.id, request)
        assert getattr(failure.value, "code", None) == "invalid_connection"


@pytest.mark.asyncio
async def test_verifier_cannot_manage_products(client: AsyncClient) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one()
        verifier = User(
            email="verifier@example.com",
            display_name="核销员",
            password_hash=hash_password("verifier-password"),
        )
        session.add(verifier)
        await session.flush()
        session.add(
            Membership(
                tenant_id=tenant.id,
                user_id=verifier.id,
                role=Role.VERIFIER.value,
            )
        )
        await session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "verifier@example.com", "password": "verifier-password"},
    )
    tenant_id = login.json()["tenants"][0]["tenant_id"]
    response = await client.post(
        "/api/v1/local-life/products",
        headers={
            "X-Tenant-ID": tenant_id,
            "X-CSRF-Token": login.json()["csrf_token"],
        },
        json=valid_product_payload(),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_auditor_can_read_products_but_cannot_mutate(client: AsyncClient) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one()
        auditor = User(
            email="product-auditor@example.com",
            display_name="商品审计员",
            password_hash=hash_password("auditor-password"),
        )
        session.add(auditor)
        await session.flush()
        session.add(
            Membership(
                tenant_id=tenant.id,
                user_id=auditor.id,
                role=Role.AUDITOR.value,
            )
        )
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "product-auditor@example.com", "password": "auditor-password"},
    )
    tenant_id = login.json()["tenants"][0]["tenant_id"]
    read = await client.get(
        "/api/v1/local-life/products", headers={"X-Tenant-ID": tenant_id}
    )
    denied = await client.post(
        "/api/v1/local-life/products",
        headers={
            "X-Tenant-ID": tenant_id,
            "X-CSRF-Token": login.json()["csrf_token"],
        },
        json=valid_product_payload(),
    )
    denied_action = await client.post(
        "/api/v1/local-life/products/missing/actions/delete",
        headers={
            "X-Tenant-ID": tenant_id,
            "X-CSRF-Token": login.json()["csrf_token"],
        },
        json={"idempotency_key": "auditor-delete-denied"},
    )
    denied_stock = await client.put(
        "/api/v1/local-life/skus/missing/stock",
        headers={
            "X-Tenant-ID": tenant_id,
            "X-CSRF-Token": login.json()["csrf_token"],
        },
        json={"stock": 1, "version": 1, "idempotency_key": "auditor-stock-denied"},
    )

    assert read.status_code == 200
    assert read.json() == []
    assert denied.status_code == 403
    assert denied_action.status_code == 403
    assert denied_stock.status_code == 403


@pytest.mark.asyncio
async def test_product_update_routes_are_durable_tenant_scoped_and_csrf_protected(
    client: AsyncClient,
) -> None:
    from .test_inventory import _seed_remote_product

    tenant_id, product_id, _ = await _seed_remote_product(client)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@example.com", "password": "operator-password"},
    )
    csrf = login.json()["csrf_token"]
    update_payload = {
        "version": 1,
        "idempotency_key": "api-product-update-v1",
        "name": "API 更新商品",
    }

    missing_csrf = await client.patch(
        f"/api/v1/local-life/products/{product_id}",
        headers={"X-Tenant-ID": tenant_id},
        json=update_payload,
    )
    accepted = await client.patch(
        f"/api/v1/local-life/products/{product_id}",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json=update_payload,
    )
    duplicate = await client.patch(
        f"/api/v1/local-life/products/{product_id}",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json=update_payload,
    )

    assert missing_csrf.status_code == 403
    assert accepted.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json()["operation_id"] == accepted.json()["operation_id"]
    assert accepted.json()["product"]["name"] == "API 更新商品"
    assert accepted.json()["product"]["version"] == 2
    assert accepted.json()["product"]["desired_state"] == "under_review"

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        operation = await session.get(
            IntegrationOperation, accepted.json()["operation_id"]
        )
        assert operation is not None
        operation.status = OperationStatus.SUCCEEDED.value
        product = await ProductService(session).get_product(tenant_id, product_id)
        assert product is not None
        product.remote_status = "approved"
        product.desired_state = "approved"
        other = Tenant(name="更新隔离租户", slug="product-update-other")
        session.add(other)
        await session.commit()
        with pytest.raises(Exception) as isolated:
            await ProductService(session).update_product(
                other.id,
                product_id,
                ProductUpdateRequest(
                    version=2,
                    idempotency_key="cross-tenant-update",
                    name="越权更新",
                ),
                audit_free=False,
            )
        assert getattr(isolated.value, "code", None) == "product_not_found"

    missing_action_csrf = await client.post(
        f"/api/v1/local-life/products/{product_id}/actions/delete",
        headers={"X-Tenant-ID": tenant_id},
        json={"idempotency_key": "action-without-csrf"},
    )
    audit_free = await client.patch(
        f"/api/v1/local-life/products/{product_id}/audit-free",
        headers={"X-Tenant-ID": tenant_id, "X-CSRF-Token": csrf},
        json={
            "version": 2,
            "idempotency_key": "api-audit-free-v2",
            "available_store_desc": "API 更新门店范围",
        },
    )

    assert missing_action_csrf.status_code == 403
    assert audit_free.status_code == 202
    assert audit_free.json()["product"]["available_store_desc"] == "API 更新门店范围"


@pytest.mark.asyncio
async def test_product_external_identifiers_are_unique_per_connection(client: AsyncClient) -> None:
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
        await session.commit()
        request = ProductCreateRequest.model_validate(valid_product_payload(connection.id))
        product, _ = await ProductService(session).create_product(tenant.id, request)
        product.external_product_id = "remote-1"
        await session.commit()

        persisted = (
            await session.execute(
                select(LocalProduct).where(LocalProduct.tenant_id == tenant.id)
            )
        ).scalar_one()
        assert persisted.connection_id == connection.id
