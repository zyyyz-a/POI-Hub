"""Local Life product services and durable remote-operation handlers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

import httpx
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
from poi_admin.operations.models import IntegrationOperation, OperationStatus
from poi_admin.operations.service import OperationService
from poi_admin.operations.worker import Handler, OperationWorker

from .models import LocalProduct, LocalSku, ProductStatus, utcnow
from .schemas import (
    ProductAction,
    ProductCreateRequest,
    ProductUpdateRequest,
    StockUpdateRequest,
)

CREATE_PRODUCT_COMMAND = "local_life.product.create"
UPDATE_PRODUCT_COMMAND = "local_life.product.update"
AUDIT_FREE_UPDATE_PRODUCT_COMMAND = "local_life.product.audit_free_update"
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

_REGULAR_UPDATE_ALLOWED_FROM = frozenset(
    {ProductStatus.DRAFT, ProductStatus.APPROVED, ProductStatus.DELISTED}
)
_AUDIT_FREE_UPDATE_ALLOWED_FROM = frozenset(
    {ProductStatus.APPROVED, ProductStatus.LISTED, ProductStatus.DELISTED}
)
_ACTIVE_OPERATION_STATUSES = frozenset(
    {
        OperationStatus.QUEUED.value,
        OperationStatus.RUNNING.value,
        OperationStatus.RETRY_WAIT.value,
    }
)


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

    async def get_product(self, tenant_id: str, product_id: str) -> LocalProduct | None:
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
        request_fingerprint = _request_fingerprint(request)
        if existing is not None:
            return await self._existing_product_operation(
                tenant_id,
                existing,
                CREATE_PRODUCT_COMMAND,
                expected_request_fingerprint=request_fingerprint,
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
            raise ProductServiceError("invalid_connection", "连接不支持微信团购商品", 422)

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
                {
                    "product_id": product.id,
                    "request_fingerprint": request_fingerprint,
                },
                connection_id=connection.id,
                resource_ref=f"local_product:{product.id}",
            )
        except IntegrityError as error:
            await self.session.rollback()
            raise ProductServiceError(
                "merchant_product_exists", "商家商品编码已存在", 409
            ) from error
        return product, operation

    async def update_product(
        self,
        tenant_id: str,
        product_id: str,
        request: ProductUpdateRequest,
        *,
        audit_free: bool,
    ) -> tuple[LocalProduct, IntegrationOperation]:
        command = AUDIT_FREE_UPDATE_PRODUCT_COMMAND if audit_free else UPDATE_PRODUCT_COMMAND
        operation_service = OperationService(self.session)
        existing = await operation_service.get_by_idempotency_key(
            tenant_id, request.idempotency_key
        )
        request_fingerprint = _request_fingerprint(request)
        if existing is not None:
            return await self._existing_product_operation(
                tenant_id,
                existing,
                command,
                expected_product_id=product_id,
                expected_request_fingerprint=request_fingerprint,
            )

        product = await self.get_product(tenant_id, product_id)
        if product is None:
            raise ProductServiceError("product_not_found", "商品不存在", 404)
        if product.external_product_id is None:
            raise ProductServiceError("product_not_ready", "商品尚未创建到微信", 409)
        await self._require_no_pending_product_operation(tenant_id, product)
        current = self._settled_product_status(product)
        allowed = _AUDIT_FREE_UPDATE_ALLOWED_FROM if audit_free else _REGULAR_UPDATE_ALLOWED_FROM
        if current not in allowed:
            raise ProductServiceError(
                "invalid_product_transition",
                f"商品状态 {current.value} 不能执行更新",
                409,
            )
        if product.version != request.version:
            raise ProductServiceError("version_conflict", "商品已被其他操作更新", 409)

        for field, value in request.changes().items():
            setattr(product, field, value)
        target = current if audit_free else ProductStatus.UNDER_REVIEW
        product.desired_state = target.value
        product.version += 1
        operation = await operation_service.enqueue(
            tenant_id,
            command,
            request.idempotency_key,
            {
                "product_id": product.id,
                "source_status": current.value,
                "target_status": target.value,
                "target_version": product.version,
                "request_fingerprint": request_fingerprint,
            },
            connection_id=product.connection_id,
            resource_ref=f"local_product:{product.id}",
        )
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
                or existing.payload.get("stock") != request.stock
            ):
                raise ProductServiceError("idempotency_key_conflict", "幂等键已用于其他操作", 409)
            existing_sku = await self.get_sku(tenant_id, sku_id)
            if existing_sku is None:
                raise ProductServiceError("sku_not_found", "SKU 不存在", 404)
            return existing_sku, existing

        sku = await self.get_sku(tenant_id, sku_id)
        if sku is None:
            raise ProductServiceError("sku_not_found", "SKU 不存在", 404)
        if sku.product.external_product_id is None or sku.external_sku_id is None:
            raise ProductServiceError("product_not_ready", "商品尚未取得微信商品与 SKU 编号", 409)
        if sku.product.remote_status == ProductStatus.DELETED.value:
            raise ProductServiceError("invalid_product_transition", "已删除商品不能更新库存", 409)
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
        existing = await operation_service.get_by_idempotency_key(tenant_id, idempotency_key)
        if existing is not None:
            if existing.command_type != command or existing.payload.get("product_id") != product_id:
                raise ProductServiceError("idempotency_key_conflict", "幂等键已用于其他操作", 409)
            return existing

        product = await self.get_product(tenant_id, product_id)
        if product is None:
            raise ProductServiceError("product_not_found", "商品不存在", 404)
        if product.external_product_id is None:
            raise ProductServiceError("product_not_ready", "商品尚未创建到微信", 409)
        await self._require_no_pending_product_operation(tenant_id, product)
        current = self._settled_product_status(product)
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
            {
                "product_id": product.id,
                "source_status": current.value,
                "target_status": _ACTION_TARGETS[resolved_action].value,
                "target_version": product.version,
            },
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

    async def _require_no_pending_product_operation(
        self, tenant_id: str, product: LocalProduct
    ) -> None:
        pending = (
            await self.session.execute(
                select(IntegrationOperation)
                .where(
                    IntegrationOperation.tenant_id == tenant_id,
                    IntegrationOperation.resource_ref == f"local_product:{product.id}",
                    IntegrationOperation.status.in_(_ACTIVE_OPERATION_STATUSES),
                )
                .order_by(IntegrationOperation.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if pending is not None:
            raise ProductServiceError("product_operation_pending", "商品已有待处理操作", 409)

    @staticmethod
    def _settled_product_status(product: LocalProduct) -> ProductStatus:
        try:
            remote_status = ProductStatus(product.remote_status)
            desired_status = ProductStatus(product.desired_state)
        except ValueError as error:
            raise ProductServiceError("invalid_product_status", "商品状态无效", 409) from error
        if desired_status != remote_status:
            raise ProductServiceError("product_state_pending", "商品目标状态尚未完成", 409)
        return remote_status

    async def _existing_product_operation(
        self,
        tenant_id: str,
        operation: IntegrationOperation,
        expected_command: str,
        *,
        expected_product_id: str | None = None,
        expected_request_fingerprint: str | None = None,
    ) -> tuple[LocalProduct, IntegrationOperation]:
        product_id = operation.payload.get("product_id")
        existing_fingerprint = operation.payload.get("request_fingerprint")
        if (
            operation.command_type != expected_command
            or not isinstance(product_id, str)
            or (expected_product_id is not None and product_id != expected_product_id)
            or (
                expected_request_fingerprint is not None
                and existing_fingerprint is not None
                and existing_fingerprint != expected_request_fingerprint
            )
        ):
            raise ProductServiceError("idempotency_key_conflict", "幂等键已用于其他操作", 409)
        product = await self.get_product(tenant_id, product_id)
        if product is None:
            raise ProductServiceError(
                "idempotency_resource_missing", "幂等操作对应的商品不存在", 409
            )
        return product, operation


def _request_fingerprint(request: ProductCreateRequest | ProductUpdateRequest) -> str:
    body = request.model_dump(exclude={"idempotency_key"}, mode="json", exclude_unset=True)
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    http_client: httpx.AsyncClient | None = None,
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
        connection_service = ConnectionService(
            session, settings, http_client=http_client
        )
        connection = await connection_service.get(operation.tenant_id, product.connection_id)
        if connection is None:
            raise GatewayTerminalError("connection was not found", code="connection_not_found")
        if connection.capability != Capability.LOCAL_LIFE.value:
            raise GatewayTerminalError(
                "connection does not support Local Life", code="invalid_connection"
            )
        return cast(
            LocalLifeGateway,
            await connection_service.gateway(operation.tenant_id, connection.id),
        )

    def validate_intent(
        product: LocalProduct, operation: IntegrationOperation
    ) -> tuple[ProductStatus, ProductStatus, ProductStatus]:
        source_value = operation.payload.get("source_status")
        target_value = operation.payload.get("target_status")
        target_version = operation.payload.get("target_version")
        if (
            not isinstance(source_value, str)
            or not isinstance(target_value, str)
            or not isinstance(target_version, int)
        ):
            raise GatewayTerminalError(
                "product operation intent is invalid", code="invalid_operation_payload"
            )
        try:
            source = ProductStatus(source_value)
            target = ProductStatus(target_value)
            current = ProductStatus(product.remote_status)
            desired = ProductStatus(product.desired_state)
        except ValueError as error:
            raise GatewayTerminalError(
                "product operation status is invalid", code="invalid_product_status"
            ) from error
        if product.version != target_version or desired != target:
            raise GatewayTerminalError(
                "product intent changed after operation was queued",
                code="product_intent_changed",
            )
        if current not in {source, target}:
            raise GatewayTerminalError(
                "product state changed after operation was queued",
                code="invalid_product_transition",
            )
        return source, target, current

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
        await gateway.update_stock(product.external_product_id, sku.external_sku_id, stock)
        sku.stock = stock
        sku.last_stock_synced_at = utcnow()
        await session.commit()
        return {"sku_id": sku.id, "stock": sku.stock, "superseded": False}

    async def apply_update(operation: IntegrationOperation) -> dict[str, Any]:
        product = await product_for(operation)
        _, target, current = validate_intent(product, operation)
        audit_free = operation.command_type == AUDIT_FREE_UPDATE_PRODUCT_COMMAND
        if not audit_free and current == target:
            return {"product_id": product.id, "remote_status": target.value}
        if product.external_product_id is None:
            raise GatewayTerminalError(
                "remote product identifier is missing", code="product_not_ready"
            )
        gateway = await gateway_for(operation, product)
        if audit_free:
            result = await gateway.audit_free_update_product(
                product.external_product_id, _product_payload(product)
            )
        else:
            result = await gateway.update_product(
                product.external_product_id, _product_payload(product)
            )
        result_status = _status(result)
        if result_status != target:
            raise GatewayTerminalError(
                "remote product did not reach the requested status",
                code="invalid_product_transition",
            )
        product.remote_status = result_status.value
        product.desired_state = result_status.value
        product.last_synced_at = utcnow()
        await session.commit()
        return {"product_id": product.id, "remote_status": product.remote_status}

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
            raise GatewayTerminalError("product action is invalid", code="invalid_product_action")
        _, target, current = validate_intent(product, operation)
        if target != _ACTION_TARGETS[action]:
            raise GatewayTerminalError(
                "product action target is invalid", code="invalid_operation_payload"
            )
        if current == target:
            return {"product_id": product.id, "remote_status": target.value}
        if product.external_product_id is None:
            raise GatewayTerminalError(
                "remote product identifier is missing", code="product_not_ready"
            )
        gateway = await gateway_for(operation, product)
        if action == ProductAction.CANCEL_AUDIT:
            result = await gateway.cancel_product_audit(product.external_product_id)
        elif action == ProductAction.LIST:
            result = await gateway.list_product(product.external_product_id)
        elif action == ProductAction.DELIST:
            result = await gateway.delist_product(product.external_product_id)
        else:
            try:
                await gateway.delete_product(product.external_product_id)
            except GatewayTerminalError as error:
                if error.code != "product_not_found":
                    raise
            product.remote_status = ProductStatus.DELETED.value
            result = None
        if result is not None:
            result_status = _status(result)
            if result_status != target:
                raise GatewayTerminalError(
                    "remote product did not reach the requested status",
                    code="invalid_product_transition",
                )
            product.remote_status = result_status.value
        product.desired_state = product.remote_status
        product.last_synced_at = utcnow()
        await session.commit()
        return {"product_id": product.id, "remote_status": product.remote_status}

    handlers: dict[str, Handler] = {
        CREATE_PRODUCT_COMMAND: create_product,
        UPDATE_PRODUCT_COMMAND: apply_update,
        AUDIT_FREE_UPDATE_PRODUCT_COMMAND: apply_update,
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
