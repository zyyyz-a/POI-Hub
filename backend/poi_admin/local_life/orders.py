"""Local Life order and after-sale mirrors plus durable sync handlers."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, cast

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from poi_admin.connections.crypto import redact_secrets
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import (
    Capability,
    GatewayTerminalError,
    LocalLifeGateway,
    VoucherResult,
)
from poi_admin.connections.service import ConnectionService
from poi_admin.core.config import Settings
from poi_admin.operations.models import IntegrationOperation
from poi_admin.operations.service import OperationService
from poi_admin.operations.worker import Handler

from .models import LocalAfterSale, LocalOrder, utcnow
from .schemas import OrderSyncRequest

ORDER_SYNC_COMMAND = "local_life.order.sync"
AFTER_SALE_SYNC_COMMAND = "local_life.after_sale.sync"


class OrderServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _checksum(value: Any) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def _safe_summary(raw: dict[str, Any]) -> dict[str, Any]:
    summary = cast(dict[str, Any], redact_secrets(raw))
    # Keep remote payloads bounded and useful to operators without retaining PII.
    result = {
        str(key): value
        for key, value in summary.items()
        if key
        in {
            "status",
            "total_amount",
            "paid_amount",
            "currency",
            "customer_reference",
            "customer_ref",
            "type",
            "refund_amount",
            "updated_at",
            "created_at",
        }
    }
    for key in ("customer_reference", "customer_ref"):
        if key in result:
            result[key] = mask_customer_reference(result[key])
    return result


def mask_customer_reference(value: Any) -> str | None:
    """Return a non-sensitive customer marker suitable for the local mirror."""

    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return "****" + normalized[-4:] if len(normalized) > 4 else "****"


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class OrderService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings

    async def _connection(self, tenant_id: str, connection_id: str) -> WeChatConnection:
        connection = (
            await self.session.execute(
                select(WeChatConnection).where(
                    WeChatConnection.tenant_id == tenant_id,
                    WeChatConnection.id == connection_id,
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            raise OrderServiceError("connection_not_found", "连接不存在", 404)
        if connection.capability != Capability.LOCAL_LIFE.value:
            raise OrderServiceError("invalid_connection", "连接不支持微信团购订单", 422)
        return connection

    async def list_orders(self, tenant_id: str) -> list[LocalOrder]:
        return list(
            (
                await self.session.execute(
                    select(LocalOrder)
                    .where(LocalOrder.tenant_id == tenant_id)
                    .options(
                        selectinload(LocalOrder.vouchers), selectinload(LocalOrder.after_sales)
                    )
                    .order_by(LocalOrder.created_at.desc(), LocalOrder.id)
                )
            )
            .scalars()
            .all()
        )

    async def get_order(self, tenant_id: str, order_id: str) -> LocalOrder | None:
        return (
            await self.session.execute(
                select(LocalOrder)
                .where(LocalOrder.tenant_id == tenant_id, LocalOrder.id == order_id)
                .options(selectinload(LocalOrder.vouchers), selectinload(LocalOrder.after_sales))
            )
        ).scalar_one_or_none()

    async def sync_order(
        self, tenant_id: str, request: OrderSyncRequest
    ) -> tuple[LocalOrder, IntegrationOperation]:
        await self._connection(tenant_id, request.connection_id)
        operation_service = OperationService(self.session)
        existing_operation = await operation_service.get_by_idempotency_key(
            tenant_id, request.idempotency_key
        )
        if existing_operation is not None and (
            existing_operation.command_type != ORDER_SYNC_COMMAND
            or existing_operation.connection_id != request.connection_id
            or existing_operation.payload.get("external_order_id")
            != request.external_order_id
        ):
            raise OrderServiceError(
                "idempotency_key_conflict", "幂等键已用于其他操作", 409
            )
        existing_order = (
            await self.session.execute(
                select(LocalOrder).where(
                    LocalOrder.tenant_id == tenant_id,
                    LocalOrder.connection_id == request.connection_id,
                    LocalOrder.external_order_id == request.external_order_id,
                )
            )
        ).scalar_one_or_none()
        if existing_order is None:
            existing_order = LocalOrder(
                tenant_id=tenant_id,
                connection_id=request.connection_id,
                external_order_id=request.external_order_id,
            )
            self.session.add(existing_order)
            await self.session.flush()
        if existing_operation is None:
            existing_operation = await operation_service.enqueue(
                tenant_id,
                ORDER_SYNC_COMMAND,
                request.idempotency_key,
                {
                    "order_id": existing_order.id,
                    "external_order_id": request.external_order_id,
                },
                connection_id=request.connection_id,
                resource_ref=f"local_order:{existing_order.id}",
            )
        return existing_order, existing_operation

    async def sync_after_sale(
        self,
        tenant_id: str,
        order_id: str,
        external_after_sale_id: str,
        idempotency_key: str,
    ) -> IntegrationOperation:
        order = await self.get_order(tenant_id, order_id)
        if order is None:
            raise OrderServiceError("order_not_found", "订单不存在", 404)
        operation_service = OperationService(self.session)
        existing = await operation_service.get_by_idempotency_key(tenant_id, idempotency_key)
        if existing is not None:
            if (
                existing.command_type != AFTER_SALE_SYNC_COMMAND
                or existing.payload.get("order_id") != order_id
                or existing.payload.get("external_after_sale_id") != external_after_sale_id
            ):
                raise OrderServiceError(
                    "idempotency_key_conflict", "幂等键已用于其他操作", 409
                )
            return existing
        after_sale = (
            await self.session.execute(
                select(LocalAfterSale).where(
                    LocalAfterSale.tenant_id == tenant_id,
                    LocalAfterSale.connection_id == order.connection_id,
                    LocalAfterSale.external_after_sale_id == external_after_sale_id,
                )
            )
        ).scalar_one_or_none()
        if after_sale is None:
            after_sale = LocalAfterSale(
                tenant_id=tenant_id,
                connection_id=order.connection_id,
                order_id=order.id,
                external_after_sale_id=external_after_sale_id,
            )
            self.session.add(after_sale)
            await self.session.flush()
        return await operation_service.enqueue(
            tenant_id,
            AFTER_SALE_SYNC_COMMAND,
            idempotency_key,
            {
                "after_sale_id": after_sale.id,
                "order_id": order.id,
                "external_after_sale_id": external_after_sale_id,
            },
            connection_id=order.connection_id,
            resource_ref=f"local_after_sale:{after_sale.id}",
        )


def order_operation_handlers(
    session: AsyncSession,
    settings: Settings | None = None,
    *,
    gateway_override: LocalLifeGateway | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Handler]:
    service = OrderService(session, settings=settings)

    async def gateway_for(operation: IntegrationOperation, connection_id: str) -> LocalLifeGateway:
        if gateway_override is not None:
            return gateway_override
        if settings is None:
            raise GatewayTerminalError(
                "gateway settings are missing", code="gateway_not_configured"
            )
        try:
            connection = await service._connection(operation.tenant_id, connection_id)
        except OrderServiceError as error:
            raise GatewayTerminalError(error.message, code=error.code) from error
        return cast(
            LocalLifeGateway,
            await ConnectionService(
                session, settings, http_client=http_client
            ).gateway(operation.tenant_id, connection.id),
        )

    async def sync_order(operation: IntegrationOperation) -> dict[str, Any]:
        order_id = operation.payload.get("order_id")
        if not isinstance(order_id, str):
            raise GatewayTerminalError("订单操作参数无效", code="invalid_operation_payload")
        order = await service.get_order(operation.tenant_id, order_id)
        if order is None:
            raise GatewayTerminalError("订单不存在", code="order_not_found")
        gateway = await gateway_for(operation, order.connection_id)
        result = await gateway.get_order(order.external_order_id)
        order.status = result.status
        order.total_amount = result.total_amount
        order.paid_amount = (
            int(result.raw.get("paid_amount", result.total_amount))
            if isinstance(result.raw, dict)
            else result.total_amount
        )
        order.currency = (
            str(result.raw.get("currency", "CNY")) if isinstance(result.raw, dict) else "CNY"
        )
        raw_customer = (
            result.raw.get("customer_reference", result.raw.get("customer_ref"))
            if isinstance(result.raw, dict)
            else None
        )
        order.customer_reference_masked = mask_customer_reference(raw_customer)
        order.raw_summary = _safe_summary(result.raw)
        order.raw_checksum = _checksum(order.raw_summary)
        order.remote_updated_at = (
            _parse_datetime(result.raw.get("updated_at")) if isinstance(result.raw, dict) else None
        )
        order.last_synced_at = utcnow()
        from .vouchers import VoucherService

        voucher_payloads = (
            result.raw.get("voucher_list", []) if isinstance(result.raw, dict) else []
        )
        voucher_results: list[VoucherResult] = []
        states = {1: "available", 2: "consumed", 3: "refunded", 4: "expired", 5: "reserved"}
        for raw_voucher in voucher_payloads:
            if not isinstance(raw_voucher, dict):
                continue
            code = raw_voucher.get("code")
            if not isinstance(code, str) or not code:
                continue
            try:
                state = states.get(int(raw_voucher.get("status", 1)), "available")
            except (TypeError, ValueError):
                state = "available"
            voucher_results.append(
                VoucherResult(
                    code,
                    state,
                    str(raw_voucher.get("product_id") or "") or None,
                    str(
                        raw_voucher.get("out_store_id")
                        or raw_voucher.get("consume_store_name")
                        or ""
                    )
                    or None,
                    raw_voucher,
                )
            )
        voucher_service = VoucherService(session, settings=settings)
        for voucher_result in voucher_results:
            await voucher_service.upsert_remote_voucher(
                operation.tenant_id,
                order.connection_id,
                voucher_result,
                order_id=order.id,
            )
        await session.commit()
        return {
            "order_id": order.id,
            "external_order_id": order.external_order_id,
            "voucher_count": len(voucher_results),
        }

    async def sync_after_sale(operation: IntegrationOperation) -> dict[str, Any]:
        after_sale_id = operation.payload.get("after_sale_id")
        if not isinstance(after_sale_id, str):
            raise GatewayTerminalError("售后操作参数无效", code="invalid_operation_payload")
        after_sale = (
            await session.execute(
                select(LocalAfterSale).where(
                    LocalAfterSale.tenant_id == operation.tenant_id,
                    LocalAfterSale.id == after_sale_id,
                )
            )
        ).scalar_one_or_none()
        if after_sale is None:
            raise GatewayTerminalError("售后记录不存在", code="after_sale_not_found")
        gateway = await gateway_for(operation, after_sale.connection_id)
        raw = await gateway.get_after_sale(after_sale.external_after_sale_id)
        safe = _safe_summary(raw)
        after_sale.status = str(raw.get("status", raw.get("state", "unknown")))
        after_sale.after_sale_type = str(raw.get("type")) if raw.get("type") is not None else None
        try:
            after_sale.refund_amount = int(raw.get("refund_amount", raw.get("amount", 0)))
        except (TypeError, ValueError):
            after_sale.refund_amount = 0
        after_sale.raw_summary = safe
        after_sale.last_synced_at = utcnow()
        await session.commit()
        return {"after_sale_id": after_sale.id, "status": after_sale.status}

    return {ORDER_SYNC_COMMAND: sync_order, AFTER_SALE_SYNC_COMMAND: sync_after_sale}


__all__ = [
    "AFTER_SALE_SYNC_COMMAND",
    "ORDER_SYNC_COMMAND",
    "OrderService",
    "OrderServiceError",
    "order_operation_handlers",
]
