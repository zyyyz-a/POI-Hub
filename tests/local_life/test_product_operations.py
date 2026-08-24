from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from poi_admin.connections.mock import MockLocalLifeGateway
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import (
    Capability,
    ConnectionMode,
    GatewayTerminalError,
    GatewayTransientError,
    ProductResult,
    SkuResult,
)
from poi_admin.identity.models import Tenant
from poi_admin.local_life.models import LocalProduct, ProductStatus
from poi_admin.local_life.products import ProductService, product_operation_handlers
from poi_admin.local_life.schemas import ProductCreateRequest, ProductUpdateRequest
from poi_admin.operations.models import IntegrationOperation, OperationStatus

from .test_products import valid_product_payload


class RecordingGateway:
    def __init__(
        self,
        *,
        fail_stock_once: bool = False,
        missing_on_delete: bool = False,
        missing_on_list: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.fail_stock_once = fail_stock_once
        self.missing_on_delete = missing_on_delete
        self.missing_on_list = missing_on_list
        self.update_payloads: list[dict[str, Any]] = []

    async def create_product(self, payload: dict[str, Any]) -> ProductResult:
        self.calls.append("create_product")
        return ProductResult(
            external_id="remote-product-1",
            name=str(payload["name"]),
            status=ProductStatus.UNDER_REVIEW.value,
            skus=(SkuResult("remote-sku-1", "BREAKFAST-001-2P"),),
        )

    async def update_stock(
        self, external_id: str, sku_id: str, stock: int
    ) -> dict[str, Any]:
        self.calls.append("update_stock")
        if self.fail_stock_once:
            self.fail_stock_once = False
            raise GatewayTransientError("temporary stock failure", code="timeout")
        return {"product_id": external_id, "sku_id": sku_id, "stock": stock}

    async def update_product(
        self, external_id: str, payload: dict[str, Any]
    ) -> ProductResult:
        self.calls.append("update_product")
        self.update_payloads.append(payload)
        return ProductResult(
            external_id,
            str(payload["name"]),
            ProductStatus.UNDER_REVIEW.value,
        )

    async def audit_free_update_product(
        self, external_id: str, payload: dict[str, Any]
    ) -> ProductResult:
        self.calls.append("audit_free_update_product")
        self.update_payloads.append(payload)
        return ProductResult(
            external_id,
            str(payload["name"]),
            ProductStatus.APPROVED.value,
        )

    async def cancel_product_audit(self, external_id: str) -> ProductResult:
        self.calls.append("cancel_product_audit")
        return ProductResult(external_id, "商品", ProductStatus.DRAFT.value)

    async def list_product(self, external_id: str) -> ProductResult:
        self.calls.append("list_product")
        if self.missing_on_list:
            raise GatewayTerminalError("missing", code="product_not_found")
        return ProductResult(external_id, "商品", ProductStatus.LISTED.value)

    async def delist_product(self, external_id: str) -> ProductResult:
        self.calls.append("delist_product")
        return ProductResult(external_id, "商品", ProductStatus.DELISTED.value)

    async def delete_product(self, external_id: str) -> None:
        self.calls.append("delete_product")
        if self.missing_on_delete:
            raise GatewayTerminalError("missing", code="product_not_found")


async def _seed_create_operation(client) -> tuple[Any, LocalProduct, IntegrationOperation]:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    session = database.session_factory()
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
    product, operation = await ProductService(session).create_product(tenant.id, request)
    return session, product, operation


@pytest.mark.asyncio
async def test_create_persists_remote_ids_before_setting_stock(client) -> None:
    session, product, operation = await _seed_create_operation(client)
    gateway = RecordingGateway()
    try:
        handler = product_operation_handlers(session, gateway_override=gateway)[
            "local_life.product.create"
        ]
        result = await handler(operation)
        await session.refresh(product)
        await session.refresh(product.skus[0])

        stock_operation = (
            await session.execute(
                select(IntegrationOperation).where(
                    IntegrationOperation.tenant_id == product.tenant_id,
                    IntegrationOperation.command_type == "local_life.inventory.set",
                )
            )
        ).scalar_one()
        assert gateway.calls == ["create_product"]
        assert product.external_product_id == "remote-product-1"
        assert product.remote_status == "under_review"
        assert product.skus[0].external_sku_id == "remote-sku-1"
        assert product.skus[0].stock == 0
        assert stock_operation.payload["stock"] == 25

        await product_operation_handlers(session, gateway_override=gateway)[
            stock_operation.command_type
        ](stock_operation)
        await session.refresh(product.skus[0])
        assert gateway.calls == ["create_product", "update_stock"]
        assert product.skus[0].stock == 25
        assert result == {
            "product_id": product.id,
            "external_product_id": "remote-product-1",
            "stock_operation_ids": [stock_operation.id],
        }
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_create_retry_does_not_create_remote_product_or_stock_jobs_twice(client) -> None:
    session, product, operation = await _seed_create_operation(client)
    gateway = RecordingGateway()
    try:
        handler = product_operation_handlers(session, gateway_override=gateway)[
            "local_life.product.create"
        ]
        await handler(operation)
        await session.refresh(product)
        assert product.external_product_id == "remote-product-1"
        await handler(operation)

        stock_operations = list(
            (
                await session.execute(
                    select(IntegrationOperation).where(
                        IntegrationOperation.tenant_id == product.tenant_id,
                        IntegrationOperation.command_type == "local_life.inventory.set",
                    )
                )
            ).scalars()
        )
        assert gateway.calls == ["create_product"]
        assert len(stock_operations) == 1
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_mock_remote_state_survives_gateway_factory_recreation() -> None:
    first = MockLocalLifeGateway("tenant-mock-regression")
    created = await first.create_product(
        {
            "merchant_product_id": "MOCK-CROSS-OP",
            "name": "跨操作商品",
            "skus": [{"merchant_sku_id": "MOCK-CROSS-SKU", "sale_price": 100}],
        }
    )
    second = MockLocalLifeGateway("tenant-mock-regression")

    updated = await second.update_stock(
        created.external_id, created.skus[0].external_id, 12
    )

    assert updated["stock"] == 12
    with pytest.raises(Exception) as unknown:
        await second.update_stock("unknown-product", "unknown-sku", 10)
    assert getattr(unknown.value, "code", None) == "product_not_found"


@pytest.mark.asyncio
async def test_product_lifecycle_transitions_are_validated_and_idempotent(client) -> None:
    session, product, create_operation = await _seed_create_operation(client)
    gateway = RecordingGateway()
    try:
        product.external_product_id = "remote-product-1"
        product.remote_status = ProductStatus.UNDER_REVIEW.value
        product.desired_state = ProductStatus.UNDER_REVIEW.value
        product.skus[0].external_sku_id = "remote-sku-1"
        create_operation.status = OperationStatus.SUCCEEDED.value
        await session.commit()
        service = ProductService(session)

        cancel = await service.enqueue_action(
            product.tenant_id, product.id, "cancel_audit", "cancel-audit-v1"
        )
        duplicate = await service.enqueue_action(
            product.tenant_id, product.id, "cancel_audit", "cancel-audit-v1"
        )
        assert duplicate.id == cancel.id
        await product_operation_handlers(session, gateway_override=gateway)[
            cancel.command_type
        ](cancel)
        assert product.remote_status == ProductStatus.DRAFT.value

        cancel.status = OperationStatus.SUCCEEDED.value
        product.remote_status = ProductStatus.APPROVED.value
        product.desired_state = ProductStatus.APPROVED.value
        await session.commit()
        listing = await service.enqueue_action(
            product.tenant_id, product.id, "list", "list-product-v1"
        )
        await product_operation_handlers(session, gateway_override=gateway)[
            listing.command_type
        ](listing)
        assert product.remote_status == ProductStatus.LISTED.value

        listing.status = OperationStatus.SUCCEEDED.value
        await session.commit()
        delisting = await service.enqueue_action(
            product.tenant_id, product.id, "delist", "delist-product-v1"
        )
        await product_operation_handlers(session, gateway_override=gateway)[
            delisting.command_type
        ](delisting)
        assert product.remote_status == ProductStatus.DELISTED.value

        delisting.status = OperationStatus.SUCCEEDED.value
        await session.commit()
        deletion = await service.enqueue_action(
            product.tenant_id, product.id, "delete", "delete-product-v1"
        )
        await product_operation_handlers(session, gateway_override=gateway)[
            deletion.command_type
        ](deletion)
        assert product.remote_status == ProductStatus.DELETED.value
        assert gateway.calls == [
            "cancel_product_audit",
            "list_product",
            "delist_product",
            "delete_product",
        ]
        deletion.status = OperationStatus.SUCCEEDED.value
        await session.commit()

        with pytest.raises(Exception) as invalid:
            await service.enqueue_action(
                product.tenant_id, product.id, "list", "list-deleted-v1"
            )
        assert getattr(invalid.value, "code", None) == "invalid_product_transition"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_regular_and_audit_free_updates_use_distinct_gateway_methods(client) -> None:
    session, product, create_operation = await _seed_create_operation(client)
    gateway = RecordingGateway()
    try:
        product.external_product_id = "remote-product-1"
        product.remote_status = ProductStatus.APPROVED.value
        product.desired_state = ProductStatus.APPROVED.value
        product.skus[0].external_sku_id = "remote-sku-1"
        create_operation.status = OperationStatus.SUCCEEDED.value
        await session.commit()
        service = ProductService(session)

        regular_request = ProductUpdateRequest(
            version=1,
            idempotency_key="regular-update-v1",
            name="更新后双人早餐",
            brand="更新品牌",
        )
        updated, regular = await service.update_product(
            product.tenant_id, product.id, regular_request, audit_free=False
        )
        duplicate_product, duplicate = await service.update_product(
            product.tenant_id, product.id, regular_request, audit_free=False
        )

        assert duplicate.id == regular.id
        assert duplicate_product.version == updated.version == 2
        assert updated.name == "更新后双人早餐"
        assert updated.desired_state == ProductStatus.UNDER_REVIEW.value
        await product_operation_handlers(session, gateway_override=gateway)[
            regular.command_type
        ](regular)
        assert gateway.calls == ["update_product"]
        assert gateway.update_payloads[0]["brand"] == "更新品牌"
        assert product.remote_status == ProductStatus.UNDER_REVIEW.value

        regular.status = OperationStatus.SUCCEEDED.value
        product.remote_status = ProductStatus.APPROVED.value
        product.desired_state = ProductStatus.APPROVED.value
        await session.commit()
        audit_free_request = ProductUpdateRequest(
            version=2,
            idempotency_key="audit-free-update-v2",
            available_store_desc="全市门店通用",
        )
        _, audit_free = await service.update_product(
            product.tenant_id,
            product.id,
            audit_free_request,
            audit_free=True,
        )
        await product_operation_handlers(session, gateway_override=gateway)[
            audit_free.command_type
        ](audit_free)

        assert gateway.calls == ["update_product", "audit_free_update_product"]
        assert product.available_store_desc == "全市门店通用"
        assert product.remote_status == ProductStatus.APPROVED.value
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_pending_delete_blocks_conflicting_list_command(client) -> None:
    session, product, create_operation = await _seed_create_operation(client)
    try:
        product.external_product_id = "remote-product-1"
        product.remote_status = ProductStatus.APPROVED.value
        product.desired_state = ProductStatus.APPROVED.value
        product.skus[0].external_sku_id = "remote-sku-1"
        create_operation.status = OperationStatus.SUCCEEDED.value
        await session.commit()
        service = ProductService(session)

        deletion = await service.enqueue_action(
            product.tenant_id, product.id, "delete", "delete-before-list"
        )
        with pytest.raises(Exception) as conflict:
            await service.enqueue_action(
                product.tenant_id, product.id, "list", "list-after-delete"
            )

        assert deletion.status == OperationStatus.QUEUED.value
        assert product.desired_state == ProductStatus.DELETED.value
        assert getattr(conflict.value, "code", None) == "product_operation_pending"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_worker_revalidates_product_state_before_remote_action(client) -> None:
    session, product, create_operation = await _seed_create_operation(client)
    gateway = RecordingGateway()
    try:
        product.external_product_id = "remote-product-1"
        product.remote_status = ProductStatus.APPROVED.value
        product.desired_state = ProductStatus.APPROVED.value
        product.skus[0].external_sku_id = "remote-sku-1"
        create_operation.status = OperationStatus.SUCCEEDED.value
        await session.commit()
        listing = await ProductService(session).enqueue_action(
            product.tenant_id, product.id, "list", "safe-list-v1"
        )
        product.remote_status = ProductStatus.UNDER_REVIEW.value
        await session.commit()

        with pytest.raises(GatewayTerminalError) as failure:
            await product_operation_handlers(session, gateway_override=gateway)[
                listing.command_type
            ](listing)

        assert failure.value.code == "invalid_product_transition"
        assert gateway.calls == []
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_delete_retry_treats_remote_not_found_as_target_reached(client) -> None:
    session, product, create_operation = await _seed_create_operation(client)
    gateway = RecordingGateway(missing_on_delete=True)
    try:
        product.external_product_id = "remote-product-1"
        product.remote_status = ProductStatus.DELISTED.value
        product.desired_state = ProductStatus.DELISTED.value
        product.skus[0].external_sku_id = "remote-sku-1"
        create_operation.status = OperationStatus.SUCCEEDED.value
        await session.commit()
        deletion = await ProductService(session).enqueue_action(
            product.tenant_id, product.id, "delete", "delete-retry-v1"
        )

        result = await product_operation_handlers(session, gateway_override=gateway)[
            deletion.command_type
        ](deletion)

        assert gateway.calls == ["delete_product"]
        assert result["remote_status"] == ProductStatus.DELETED.value
        assert product.remote_status == ProductStatus.DELETED.value
        assert product.desired_state == ProductStatus.DELETED.value
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_non_delete_not_found_remains_terminal(client) -> None:
    session, product, create_operation = await _seed_create_operation(client)
    gateway = RecordingGateway(missing_on_list=True)
    try:
        product.external_product_id = "remote-product-1"
        product.remote_status = ProductStatus.APPROVED.value
        product.desired_state = ProductStatus.APPROVED.value
        product.skus[0].external_sku_id = "remote-sku-1"
        create_operation.status = OperationStatus.SUCCEEDED.value
        await session.commit()
        listing = await ProductService(session).enqueue_action(
            product.tenant_id, product.id, "list", "missing-list-v1"
        )

        with pytest.raises(GatewayTerminalError) as failure:
            await product_operation_handlers(session, gateway_override=gateway)[
                listing.command_type
            ](listing)

        assert failure.value.code == "product_not_found"
        assert product.remote_status == ProductStatus.APPROVED.value
    finally:
        await session.close()
