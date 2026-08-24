"""Operation center endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, require_csrf, require_permission
from poi_admin.core.permissions import Permission

from .models import IntegrationOperation
from .schemas import (
    BatchRetryItemResponse,
    BatchRetryRequest,
    BatchRetryResponse,
    OperationResponse,
)
from .service import OperationService

operation_router = APIRouter(prefix="/operations", tags=["operations"])


@operation_router.get("", response_model=list[OperationResponse])
async def list_operations(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_OPERATIONS))],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[OperationResponse]:
    if context.tenant is None:
        raise HTTPException(
            status_code=400, detail={"code": "tenant_required", "message": "请先选择租户"}
        )
    operations = (
        (
            await session.execute(
                select(IntegrationOperation)
                .where(IntegrationOperation.tenant_id == context.tenant.id)
                .order_by(IntegrationOperation.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [OperationResponse.model_validate(item) for item in operations]


@operation_router.post("/retry-batch", response_model=BatchRetryResponse)
async def retry_operations_batch(
    payload: BatchRetryRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_OPERATIONS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchRetryResponse:
    del csrf_context
    if context.tenant is None:
        raise HTTPException(
            status_code=400, detail={"code": "tenant_required", "message": "请先选择租户"}
        )
    results = await OperationService(session).manual_retry_many(
        context.tenant.id, payload.operation_ids
    )
    items = [
        BatchRetryItemResponse(
            operation_id=item.operation_id,
            accepted=item.accepted,
            reason=item.reason,
        )
        for item in results
    ]
    accepted_count = sum(item.accepted for item in results)
    return BatchRetryResponse(
        accepted_count=accepted_count,
        rejected_count=len(results) - accepted_count,
        items=items,
    )


@operation_router.post("/{operation_id}/retry", response_model=OperationResponse)
async def retry_operation(
    operation_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_OPERATIONS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OperationResponse:
    del csrf_context
    if context.tenant is None:
        raise HTTPException(
            status_code=400, detail={"code": "tenant_required", "message": "请先选择租户"}
        )
    try:
        operation = await OperationService(session).manual_retry(context.tenant.id, operation_id)
    except ValueError as error:
        raise HTTPException(
            status_code=404, detail={"code": "operation_not_retryable", "message": str(error)}
        ) from error
    return OperationResponse.model_validate(operation)


__all__ = ["operation_router"]
