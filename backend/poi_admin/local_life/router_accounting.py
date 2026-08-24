"""HTTP endpoints for Local Life funds, bills, and reconciliation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, auth_error, require_csrf, require_permission
from poi_admin.core.permissions import Permission
from poi_admin.operations.models import IntegrationOperation, OperationStatus

from .accounting import AccountingService, AccountingServiceError
from .models import FundsFlow, VoucherBill
from .schemas import (
    AccountingAcceptedResponse,
    AccountingEntryResponse,
    AccountingSyncRequest,
    OperationResponse,
    ReconciliationSummary,
)

accounting_router = APIRouter(prefix="/local-life", tags=["local-life-accounting"])


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


def _fund_response(item: FundsFlow) -> AccountingEntryResponse:
    return AccountingEntryResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        connection_id=item.connection_id,
        external_id=item.external_entry_id,
        entry_type=item.entry_type,
        amount=item.amount,
        currency=item.currency,
        occurred_at=item.occurred_at,
    )


def _bill_response(item: VoucherBill) -> AccountingEntryResponse:
    return AccountingEntryResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        connection_id=item.connection_id,
        external_id=item.external_bill_id,
        entry_type=item.bill_type,
        amount=item.amount,
        currency=item.currency,
        occurred_at=item.occurred_at,
    )


@accounting_router.get("/funds", response_model=list[AccountingEntryResponse])
async def list_funds(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ACCOUNTING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AccountingEntryResponse]:
    return [
        _fund_response(item)
        for item in await AccountingService(session).list_funds(_tenant_id(context))
    ]


@accounting_router.get("/bills", response_model=list[AccountingEntryResponse])
async def list_bills(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ACCOUNTING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AccountingEntryResponse]:
    return [
        _bill_response(item)
        for item in await AccountingService(session).list_bills(_tenant_id(context))
    ]


@accounting_router.get("/accounting/reconciliation", response_model=ReconciliationSummary)
async def reconciliation(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ACCOUNTING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReconciliationSummary:
    return ReconciliationSummary(
        **await AccountingService(session).reconciliation_summary(_tenant_id(context))
    )


@accounting_router.post(
    "/accounting/sync",
    response_model=AccountingAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_accounting(
    payload: AccountingSyncRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ORDERS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccountingAcceptedResponse:
    del csrf_context
    try:
        operation = await AccountingService(session).sync_accounting(
            _tenant_id(context),
            payload.connection_id,
            payload.product_id,
            payload.bill_date,
            payload.idempotency_key,
        )
    except AccountingServiceError as error:
        raise auth_error(error.code, error.message, error.status_code)
    summary = await AccountingService(session).reconciliation_summary(_tenant_id(context))
    return AccountingAcceptedResponse(
        operation=_operation(operation), summary=ReconciliationSummary(**summary)
    )


__all__ = ["accounting_router"]
