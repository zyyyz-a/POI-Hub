"""HTTP endpoints for Local Life orders, vouchers, and after-sales."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, auth_error, require_csrf, require_permission
from poi_admin.core.permissions import Permission
from poi_admin.operations.models import IntegrationOperation, OperationStatus

from .models import LocalAfterSale
from .orders import OrderService, OrderServiceError
from .schemas import (
    AfterSaleResponse,
    AfterSaleSyncRequest,
    ConsumeVoucherRequest,
    OperationResponse,
    OrderAcceptedResponse,
    OrderResponse,
    OrderSyncRequest,
    RevokeVoucherRequest,
    VoucherAcceptedResponse,
    VoucherResponse,
)
from .vouchers import VoucherService, VoucherServiceError

order_router = APIRouter(prefix="/local-life", tags=["local-life-orders"])


def _tenant_id(context: AuthContext) -> str:
    if context.tenant is None:
        raise auth_error("tenant_required", "请先选择租户", 400)
    return context.tenant.id


def _operation(operation: IntegrationOperation) -> OperationResponse:
    return OperationResponse(
        id=operation.id,
        status=OperationStatus(operation.status),
        command_type=operation.command_type,
    )


def _raise(error: Exception) -> None:
    if isinstance(error, (OrderServiceError, VoucherServiceError)):
        raise auth_error(error.code, error.message, error.status_code)
    raise error


@order_router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ORDERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[OrderResponse]:
    return [
        OrderResponse.model_validate(item)
        for item in await OrderService(session).list_orders(_tenant_id(context))
    ]


@order_router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ORDERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderResponse:
    order = await OrderService(session).get_order(_tenant_id(context), order_id)
    if order is None:
        raise auth_error("order_not_found", "订单不存在", 404)
    return OrderResponse.model_validate(order)


@order_router.post(
    "/orders/sync", response_model=OrderAcceptedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def sync_order(
    payload: OrderSyncRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ORDERS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderAcceptedResponse:
    del csrf_context
    try:
        order, operation = await OrderService(session).sync_order(_tenant_id(context), payload)
    except OrderServiceError as error:
        _raise(error)
    return OrderAcceptedResponse(
        operation=_operation(operation), order=OrderResponse.model_validate(order)
    )


@order_router.get("/vouchers", response_model=list[VoucherResponse])
async def list_vouchers(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ORDERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
    order_id: str | None = None,
) -> list[VoucherResponse]:
    return [
        VoucherResponse.model_validate(item)
        for item in await VoucherService(session).list_vouchers(
            _tenant_id(context), order_id=order_id
        )
    ]


@order_router.get("/vouchers/{voucher_id}", response_model=VoucherResponse)
async def get_voucher(
    voucher_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ORDERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VoucherResponse:
    voucher = await VoucherService(session).get_voucher(_tenant_id(context), voucher_id)
    if voucher is None:
        raise auth_error("voucher_not_found", "券码不存在", 404)
    return VoucherResponse.model_validate(voucher)


@order_router.post(
    "/vouchers/{voucher_id}/consume",
    response_model=VoucherAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def consume_voucher(
    voucher_id: str,
    payload: ConsumeVoucherRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.CONSUME_VOUCHERS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VoucherAcceptedResponse:
    del csrf_context
    tenant_id = _tenant_id(context)
    service = VoucherService(session)
    try:
        operation = await service.enqueue_consume(
            tenant_id,
            voucher_id,
            payload.store_id,
            payload.idempotency_key or f"consume:{voucher_id}:{payload.store_id}",
            reserve_no=payload.reserve_no,
        )
    except VoucherServiceError as error:
        _raise(error)
    voucher = await service.get_voucher(tenant_id, voucher_id)
    if voucher is None:
        raise auth_error("voucher_not_found", "券码不存在", 404)
    return VoucherAcceptedResponse(
        operation=_operation(operation), voucher=VoucherResponse.model_validate(voucher)
    )


@order_router.post(
    "/vouchers/{voucher_id}/revoke",
    response_model=VoucherAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def revoke_voucher(
    voucher_id: str,
    payload: RevokeVoucherRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.CONSUME_VOUCHERS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VoucherAcceptedResponse:
    del csrf_context
    tenant_id = _tenant_id(context)
    service = VoucherService(session)
    try:
        operation = await service.enqueue_revoke(
            tenant_id,
            voucher_id,
            payload.idempotency_key or f"revoke:{voucher_id}:{payload.store_id or ''}",
            store_id=payload.store_id,
        )
    except VoucherServiceError as error:
        _raise(error)
    voucher = await service.get_voucher(tenant_id, voucher_id)
    if voucher is None:
        raise auth_error("voucher_not_found", "券码不存在", 404)
    return VoucherAcceptedResponse(
        operation=_operation(operation), voucher=VoucherResponse.model_validate(voucher)
    )


@order_router.get("/after-sales", response_model=list[AfterSaleResponse])
async def list_after_sales(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ORDERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AfterSaleResponse]:
    rows = (
        (
            await session.execute(
                select(LocalAfterSale).where(LocalAfterSale.tenant_id == _tenant_id(context))
            )
        )
        .scalars()
        .all()
    )
    return [AfterSaleResponse.model_validate(item) for item in rows]


@order_router.get("/after-sales/{after_sale_id}", response_model=AfterSaleResponse)
async def get_after_sale(
    after_sale_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ORDERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AfterSaleResponse:
    row = (
        await session.execute(
            select(LocalAfterSale).where(
                LocalAfterSale.tenant_id == _tenant_id(context), LocalAfterSale.id == after_sale_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise auth_error("after_sale_not_found", "售后记录不存在", 404)
    return AfterSaleResponse.model_validate(row)


@order_router.post(
    "/after-sales/sync", response_model=OperationResponse, status_code=status.HTTP_202_ACCEPTED
)
async def sync_after_sale(
    payload: AfterSaleSyncRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_AFTER_SALES))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OperationResponse:
    del csrf_context
    try:
        operation = await OrderService(session).sync_after_sale(
            _tenant_id(context),
            payload.order_id,
            payload.external_after_sale_id,
            payload.idempotency_key,
        )
    except OrderServiceError as error:
        _raise(error)
    return _operation(operation)


__all__ = ["order_router"]
