"""HTTP endpoints for Local Life products and SKU inventory."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, auth_error, require_csrf, require_permission
from poi_admin.core.permissions import Permission
from poi_admin.operations.models import OperationStatus

from .products import ProductService, ProductServiceError
from .schemas import (
    ProductAcceptedResponse,
    ProductAction,
    ProductActionRequest,
    ProductCreateRequest,
    ProductResponse,
    ProductUpdateRequest,
    SkuResponse,
    StockAcceptedResponse,
    StockUpdateRequest,
)

product_router = APIRouter(prefix="/local-life", tags=["local-life-products"])


def _tenant_id(context: AuthContext) -> str:
    if context.tenant is None:
        raise auth_error("tenant_required", "请先选择租户", 400)
    return context.tenant.id


def _raise(error: ProductServiceError) -> None:
    raise auth_error(error.code, error.message, error.status_code)


@product_router.get("/products", response_model=list[ProductResponse])
async def list_products(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_PRODUCTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProductResponse]:
    products = await ProductService(session).list_products(_tenant_id(context))
    return [ProductResponse.model_validate(product) for product in products]


@product_router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_PRODUCTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductResponse:
    product = await ProductService(session).get_product(_tenant_id(context), product_id)
    if product is None:
        raise auth_error("product_not_found", "商品不存在", 404)
    return ProductResponse.model_validate(product)


@product_router.post(
    "/products",
    response_model=ProductAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_product(
    payload: ProductCreateRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_PRODUCTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductAcceptedResponse:
    del csrf_context
    try:
        product, operation = await ProductService(session).create_product(
            _tenant_id(context), payload
        )
    except ProductServiceError as error:
        _raise(error)
    return ProductAcceptedResponse(
        operation_id=operation.id,
        status=OperationStatus(operation.status),
        product=ProductResponse.model_validate(product),
    )


async def _update_product(
    product_id: str,
    payload: ProductUpdateRequest,
    *,
    audit_free: bool,
    context: AuthContext,
    session: AsyncSession,
) -> ProductAcceptedResponse:
    try:
        product, operation = await ProductService(session).update_product(
            _tenant_id(context), product_id, payload, audit_free=audit_free
        )
    except ProductServiceError as error:
        _raise(error)
    return ProductAcceptedResponse(
        operation_id=operation.id,
        status=OperationStatus(operation.status),
        product=ProductResponse.model_validate(product),
    )


@product_router.patch(
    "/products/{product_id}",
    response_model=ProductAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_product(
    product_id: str,
    payload: ProductUpdateRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_PRODUCTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductAcceptedResponse:
    del csrf_context
    return await _update_product(
        product_id, payload, audit_free=False, context=context, session=session
    )


@product_router.patch(
    "/products/{product_id}/audit-free",
    response_model=ProductAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def audit_free_update_product(
    product_id: str,
    payload: ProductUpdateRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_PRODUCTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductAcceptedResponse:
    del csrf_context
    return await _update_product(
        product_id, payload, audit_free=True, context=context, session=session
    )


@product_router.post(
    "/products/{product_id}/actions/{action}",
    response_model=ProductAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def product_action(
    product_id: str,
    action: ProductAction,
    payload: ProductActionRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_PRODUCTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductAcceptedResponse:
    del csrf_context
    service = ProductService(session)
    tenant_id = _tenant_id(context)
    try:
        operation = await service.enqueue_action(
            tenant_id, product_id, action, payload.idempotency_key
        )
    except ProductServiceError as error:
        _raise(error)
    product = await service.get_product(tenant_id, product_id)
    if product is None:
        raise auth_error("product_not_found", "商品不存在", 404)
    return ProductAcceptedResponse(
        operation_id=operation.id,
        status=OperationStatus(operation.status),
        product=ProductResponse.model_validate(product),
    )


@product_router.put(
    "/skus/{sku_id}/stock",
    response_model=StockAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_stock(
    sku_id: str,
    payload: StockUpdateRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_INVENTORY))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StockAcceptedResponse:
    del csrf_context
    try:
        sku, operation = await ProductService(session).update_stock(
            _tenant_id(context), sku_id, payload
        )
    except ProductServiceError as error:
        _raise(error)
    return StockAcceptedResponse(
        operation_id=operation.id,
        status=OperationStatus(operation.status),
        sku=SkuResponse.model_validate(sku),
    )


__all__ = ["product_router"]
