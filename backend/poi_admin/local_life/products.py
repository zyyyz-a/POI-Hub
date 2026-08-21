"""Local Life product services and durable remote-operation handlers."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import (
    Capability,
    GatewayTerminalError,
    LocalLifeGateway,
    ProductResult,
)
from poi_admin.connections.service import ConnectionService
from poi_admin.core.config import Settings
from poi_admin.operations.models import IntegrationOperation
from poi_admin.operations.service import OperationService
from poi_admin.operations.worker import Handler, OperationWorker

from .models import LocalProduct, LocalSku, ProductStatus, utcnow
from .schemas import ProductAction, ProductCreateRequest, StockUpdateRequest

CREATE_PRODUCT_COMMAND = "local_life.product.create"
SET_STOCK_COMMAND = "local_life.inventory.set"
ACTION_COMMANDS = {
    ProductAction.CANCEL_AUDIT: "local_life.product.cancel_audit",
    ProductAction.LIST: "local_life.product.list",
    ProductAction.DELIST: "local_life.product.delist",
    ProductAction.DELETE: "local_life.product.delete",
}

_ACTION_TARGETS = {
    ProductAction.CANCEL_AUDIT: ProductStatus.DRAFT,
    ProductAction.LIST: ProductStatus.LISTED,
    ProductAction.DELIST: ProductStatus.DELISTED,
    ProductAction.DELETE: ProductStatus.DELETED,
}

_ACTION_ALLOWED_FROM = {
    ProductAction.CANCEL_AUDIT: frozenset({ProductStatus.UNDER_REVIEW}),
    ProductAction.LIST: frozenset({ProductStatus.APPROVED, ProductStatus.DELISTED}),
    ProductAction.DELIST: frozenset({ProductStatus.LISTED}),
    ProductAction.DELETE: frozenset(
        {ProductStatus.DRAFT, ProductStatus.APPROVED, ProductStatus.DELISTED}
    ),
}


class ProductServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ProductService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings

    async def list_products(self, tenant_id: str) -> list[LocalProduct]:
        return list(
            (
                await self.session.execute(
                    select(LocalProduct)
                    .where(LocalProduct.tenant_id == tenant_id)
                    .options(selectinload(LocalProduct.skus))
                    .order_by(LocalProduct.created_at.desc(), LocalProduct.id)
                )
            )
            .scalars()
            .all()
        )

    async def get_product(
        self, tenant_id: str, product_id: str
    ) -> LocalProduct | None:
        return (
            await self.session.execute(
                select(LocalProduct)
                .where(
                    LocalProduct.tenant_id == tenant_id,
                    LocalProduct.id == product_id,
                )
                .options(selectinload(LocalProduct.skus))
            )
        ).scalar_one_or_none()

    async def get_sku(self, tenant_id: str, sku_id: str) -> LocalSku | None:
        return (
            await self.session.execute(
                select(LocalSku)
                .where(LocalSku.tenant_id == tenant_id, LocalSku.id == sku_id)
                .options(selectinload(LocalSku.product))
            )
        ).scalar_one_or_none()

    async def create_product(
        self, tenant_id: str, request: ProductCreateRequest
    ) -> tuple[LocalProduct, IntegrationOperation]:
        operation_service = OperationService(self.session)
        existing = await operation_service.get_by_idempotency_key(
            tenant_id, request.idempotency_key
        )
        if existing is not None:
            return await self._existing_product_operation(
                tenant_id, existing, CREATE_PRODUCT_COMMAND
            )

        connection = (
            await self.session.execute(
                select(WeChatConnection).where(
                    WeChatConnection.tenant_id == tenant_id,
                    WeChatConnection.id == request.connection_id,
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            raise ProductServiceError("connection_not_found", "连接不存在", 404)
        if connection.capability != Capability.LOCAL_LIFE.value:
            raise ProductServiceError(
                "invalid_connection", "连接不支持微信团购商品", 422
            )

        product = LocalProduct(
            tenant_id=tenant_id,
            connection_id=connection.id,
            merchant_product_id=request.merchant_product_id,
            product_type=request.product_type,
            name=request.name,
            category=request.category,
            brand=request.brand,
            head_images=request.head_images,
            available_store_desc=request.available_store_desc,
            verification_settings=request.verification_settings,
            code_source=request.code_source,
            rules=request.rules,
            remote_status=ProductStatus.PENDING_CREATE.value,
            desired_state=ProductStatus.UNDER_REVIEW.value,
            skus=[
                LocalSku(
                    tenant_id=tenant_id,
                    merchant_sku_id=sku.merchant_sku_id,
                    name=sku.name,
                    sale_price=sku.sale_price,
                    market_price=sku.market_price,
                    stock=0,
                    desired_stock=sku.stock,
                )
                for sku in request.skus
            ],
        )
        self.session.add(product)
        try:
            await self.session.flush()
            operation = await operation_service.enqueue(
                tenant_id,
                CREATE_PRODUCT_COMMAND,
                request.idempotency_key,
                {"product_id": product.id},
                connection_id=connection.id,
                resource_ref=f"local_product:{product.id}",
            )
        except IntegrityError as error:
            await self.session.rollback()
            raise ProductServiceError(
                "merchant_product_exists", "商家商品编码已存在", 409
            ) from error
        return product, operation

    async def update_stock(
        self, tenant_id: str, sku_id: str, request: StockUpdateRequest
    ) -> tuple[LocalSku, IntegrationOperation]:
        operation_service = OperationService(self.session)
        existing = await operation_service.get_by_idempotency_key(
            tenant_id, request.idempotency_key
        )
        if existing is not None:
            if (
                existing.command_type != SET_STOCK_COMMAND
                or existing.payload.get("sku_id") != sku_id
            ):
                raise ProductServiceError(
                    "idempotency_key_conflict", "幂等键已用于其他操作", 409
                )
            existing_sku = await self.get_sku(tenant_id, sku_id)
            if existing_sku is None:
                raise ProductServiceError("sku_not_found", "SKU 不存在", 404)
            return existing_sku, existing

        sku = await self.get_sku(tenant_id, sku_id)
        if sku is None:
            raise ProductServiceError("sku_not_found", "SKU 不存在", 404)
        if sku.product.external_product_id is None or sku.external_sku_id is None:
            raise ProductServiceError(
                "product_not_ready", "商品尚未取得微信商品与 SKU 编号", 409
            )
        if sku.product.remote_status == ProductStatus.DELETED.value:
            raise ProductServiceError(
                "invalid_product_transition", "已删除商品不能更新库存", 409
            )
        if sku.version != request.version:
            raise ProductServiceError("version_conflict", "库存已被其他操作更新", 409)

        sku.desired_stock = request.stock
        sku.version += 1
        operation = await operation_service.enqueue(
            tenant_id,
            SET_STOCK_COMMAND,
            request.idempotency_key,
            {
                "product_id": sku.product_id,
                "sku_id": sku.id,
                "stock": request.stock,
                "target_version": sku.version,
            },
            connection_id=sku.product.connection_id,
            resource_ref=f"local_sku:{sku.id}",
        )
        return sku, operation

    async def enqueue_action(
        self,
        tenant_id: str,
        product_id: str,
        action: ProductAction | str,
        idempotency_key: str,
    ) -> IntegrationOperation:
        try:
            resolved_action = action if isinstance(action, ProductAction) else ProductAction(action)
        except ValueError as error:
            raise ProductServiceError("invalid_product_action", "商品操作不受支持", 422) from error

        command = ACTION_COMMANDS[resolved_action]
        operation_service = OperationService(self.session)
        existing = await operation_service.get_by_idempotency_key(
            tenant_id, idempotency_key
        )
        if existing is not None:
            if (
                existing.command_type != command
                or existing.payload.get("product_id") != product_id
            ):
                raise ProductServiceError(
                    "idempotency_key_conflict", "幂等键已用于其他操作", 409
                )
            return existing

        product = await self.get_product(tenant_id, product_id)
        if product is None:
            raise ProductServiceError("product_not_found", "商品不存在", 404)
        if product.external_product_id is None:
            raise ProductServiceError("product_not_ready", "商品尚未创建到微信", 409)
        current = ProductStatus(product.remote_status)
        if current not in _ACTION_ALLOWED_FROM[resolved_action]:
            raise ProductServiceError(
                "invalid_product_transition",
                f"商品状态 {current.value} 不能执行 {resolved_action.value}",
                409,
            )

        product.desired_state = _ACTION_TARGETS[resolved_action].value
        product.version += 1
        return await operation_service.enqueue(
            tenant_id,
            command,
            idempotency_key,
            {"product_id": product.id},
            connection_id=product.connection_id,
            resource_ref=f"local_product:{product.id}",
        )

    async def run_next_operation(self) -> IntegrationOperation | None:
        if self.settings is None:
            raise RuntimeError("settings are required to run product operations")
        worker = OperationWorker(
            self.session,
            handlers=product_operation_handlers(self.session, self.settings),
        )
        return await worker.run_once()

    async def _existing_product_operation(
        self,
        tenant_id: str,
        operation: IntegrationOperation,
        expected_command: str,
    ) -> tuple[LocalProduct, IntegrationOperation]:
        product_id = operation.payload.get("product_id")
        if operation.command_type != expected_command or not isinstance(product_id, str):
            raise ProductServiceError(
                "idempotency_key_conflict", "幂等键已用于其他操作", 409
            )
        product = await self.get_product(tenant_id, product_id)
        if product is None:
            raise ProductServiceError(
                "idempotency_resource_missing", "幂等操作对应的商品不存在", 409
            )
        return product, operation


def _product_payload(product: LocalProduct) -> dict[str, Any]:
    return {
        "merchant_product_id": product.merchant_product_id,
        "name": product.name,
        "product_type": product.product_type,
        "category": product.category,
        "brand": product.brand,
        "head_images": product.head_images,
        "available_store_desc": product.available_store_desc,
        "verification_settings": product.verification_settings,
        "code_source": product.code_source,
        "rules": product.rules,
        "skus": [
            {
                "merchant_sku_id": sku.merchant_sku_id,
                "name": sku.name,
                "sale_price": sku.sale_price,
                "market_price": sku.market_price,
            }
            for sku in product.skus
        ],
    }


def _status(result: ProductResult) -> ProductStatus:
    try:
        return ProductStatus(result.status)
    except ValueError as error:
        raise GatewayTerminalError(
            "remote product returned an unknown status", code="invalid_product_status"
        ) from error


def product_operation_handlers(
    session: AsyncSession,
    settings: Settings | None = None,
    *,
    gateway_override: LocalLifeGateway | None = None,
) -> dict[str, Handler]:
    service = ProductService(session)

    async def product_for(operation: IntegrationOperation) -> LocalProduct:
        product_id = operation.payload.get("product_id")
        if not isinstance(product_id, str):
            raise GatewayTerminalError(
                "product operation is missing product_id", code="invalid_operation_payload"
            )
        product = await service.get_product(operation.tenant_id, product_id)
        if product is None:
            raise GatewayTerminalError("product was not found", code="product_not_found")
        if operation.connection_id != product.connection_id:
            raise GatewayTerminalError(
                "operation connection does not own product", code="invalid_connection"
            )
        return product

    async def gateway_for(
        operation: IntegrationOperation, product: LocalProduct
    ) -> LocalLifeGateway:
        if gateway_override is not None:
            return gateway_override
        if settings is None:
            raise GatewayTerminalError(
                "gateway settings are missing", code="gateway_not_configured"
            )
        connection_service = ConnectionService(session, settings)
        connection = await connection_service.get(
            operation.tenant_id, product.connection_id
        )
        if connection is None:
            raise GatewayTerminalError(
                "connection was not found", code="connection_not_found"
            )
        if connection.capability != Capability.LOCAL_LIFE.value:
            raise GatewayTerminalError(
                "connection does not support Local Life", code="invalid_connection"
            )
        return cast(
            LocalLifeGateway,
            await connection_service.gateway(operation.tenant_id, connection.id),
        )

    async def create_product(operation: IntegrationOperation) -> dict[str, Any]:
        product = await product_for(operation)
        gateway = await gateway_for(operation, product)
        if product.external_product_id is None:
            result = await gateway.create_product(_product_payload(product))
            if len(result.skus) != len(product.skus):
                raise GatewayTerminalError(
                    "remote SKU identifiers do not match the request",
                    code="remote_sku_mismatch",
                )
            remote_by_merchant = {
                sku.merchant_sku_id: sku.external_id
                for sku in result.skus
                if sku.merchant_sku_id is not None
            }
            remote_ids = [
                remote_by_merchant.get(local.merchant_sku_id, remote.external_id)
                for local, remote in zip(product.skus, result.skus, strict=True)
            ]
            if any(not remote_id for remote_id in remote_ids) or len(set(remote_ids)) != len(
                remote_ids
            ):
                raise GatewayTerminalError(
                    "remote SKU identifiers are invalid", code="remote_sku_mismatch"
                )
            product.external_product_id = result.external_id
            product.remote_status = _status(result).value
            product.last_synced_at = utcnow()
            for local_sku, remote_id in zip(product.skus, remote_ids, strict=True):
                local_sku.external_sku_id = remote_id
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise GatewayTerminalError(
                    "remote identifiers already belong to another product",
                    code="remote_identifier_conflict",
                ) from error

        if product.external_product_id is None or any(
            sku.external_sku_id is None for sku in product.skus
        ):
            raise GatewayTerminalError(
                "remote product identifiers are incomplete", code="remote_sku_mismatch"
            )

        stock_operation_ids: list[str] = []
        operation_service = OperationService(session)
        for sku in product.skus:
            stock_operation = await operation_service.enqueue(
                operation.tenant_id,
                SET_STOCK_COMMAND,
                f"initial-stock:{product.id}:{sku.id}:v{sku.version}",
                {
                    "product_id": product.id,
                    "sku_id": sku.id,
                    "stock": sku.desired_stock,
                    "target_version": sku.version,
                },
                connection_id=product.connection_id,
                resource_ref=f"local_sku:{sku.id}",
            )
            stock_operation_ids.append(stock_operation.id)
        return {
            "product_id": product.id,
            "external_product_id": product.external_product_id,
            "stock_operation_ids": stock_operation_ids,
        }

    async def set_stock(operation: IntegrationOperation) -> dict[str, Any]:
        sku_id = operation.payload.get("sku_id")
        stock = operation.payload.get("stock")
        target_version = operation.payload.get("target_version")
        if (
            not isinstance(sku_id, str)
            or not isinstance(stock, int)
            or not isinstance(target_version, int)
            or stock < 0
        ):
            raise GatewayTerminalError(
                "stock operation payload is invalid", code="invalid_operation_payload"
            )
        sku = await service.get_sku(operation.tenant_id, sku_id)
        if sku is None:
            raise GatewayTerminalError("SKU was not found", code="sku_not_found")
        product = sku.product
        if operation.connection_id != product.connection_id:
            raise GatewayTerminalError(
                "operation connection does not own SKU", code="invalid_connection"
            )
        if sku.version != target_version:
            return {"sku_id": sku.id, "stock": sku.stock, "superseded": True}
        if product.external_product_id is None or sku.external_sku_id is None:
            raise GatewayTerminalError(
                "remote product identifiers are incomplete", code="product_not_ready"
            )
        gateway = await gateway_for(operation, product)
        await gateway.update_stock(
            product.external_product_id, sku.external_sku_id, stock
        )
        sku.stock = stock
        sku.last_stock_synced_at = utcnow()
        await session.commit()
        return {"sku_id": sku.id, "stock": sku.stock, "superseded": False}

    async def apply_action(operation: IntegrationOperation) -> dict[str, Any]:
        product = await product_for(operation)
        action = next(
            (
                candidate
                for candidate, command in ACTION_COMMANDS.items()
                if command == operation.command_type
            ),
            None,
        )
        if action is None:
            raise GatewayTerminalError(
                "product action is invalid", code="invalid_product_action"
            )
        target = _ACTION_TARGETS[action]
        if product.remote_status == target.value:
            return {"product_id": product.id, "remote_status": target.value}
        if product.external_product_id is None:
            raise GatewayTerminalError(
                "remote product identifier is missing", code="product_not_ready"
            )
        gateway = await gateway_for(operation, product)
        if action == ProductAction.CANCEL_AUDIT:
            result = await gateway.cancel_product_audit(product.external_product_id)
            product.remote_status = _status(result).value
        elif action == ProductAction.LIST:
            result = await gateway.list_product(product.external_product_id)
            product.remote_status = _status(result).value
        elif action == ProductAction.DELIST:
            result = await gateway.delist_product(product.external_product_id)
            product.remote_status = _status(result).value
        else:
            await gateway.delete_product(product.external_product_id)
            product.remote_status = ProductStatus.DELETED.value
        product.desired_state = product.remote_status
        product.last_synced_at = utcnow()
        await session.commit()
        return {"product_id": product.id, "remote_status": product.remote_status}

    handlers: dict[str, Handler] = {
        CREATE_PRODUCT_COMMAND: create_product,
        SET_STOCK_COMMAND: set_stock,
    }
    handlers.update({command: apply_action for command in ACTION_COMMANDS.values()})
    return handlers


__all__ = [
    "ACTION_COMMANDS",
    "CREATE_PRODUCT_COMMAND",
    "ProductService",
    "ProductServiceError",
    "SET_STOCK_COMMAND",
    "product_operation_handlers",
]
