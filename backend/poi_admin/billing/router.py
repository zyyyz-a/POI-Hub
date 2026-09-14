"""Platform SaaS billing endpoints for plans, subscriptions, invoices, and payments."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, auth_error, require_csrf, require_permission
from poi_admin.core.permissions import Permission

from .schemas import (
    AdjustmentCreate,
    AdjustmentResponse,
    BillingSummaryResponse,
    InvoiceGenerate,
    InvoiceItemResponse,
    InvoiceResponse,
    PaymentCreate,
    PaymentResponse,
    PlanCreate,
    PlanResponse,
    PlanUpdate,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
    UsageEventCreate,
    UsageEventResponse,
)
from .service import BillingError, BillingService

billing_router = APIRouter(prefix="/billing", tags=["billing"])


def _raise(error: BillingError) -> None:
    raise auth_error(error.code, error.message, error.status_code)


def _scope_tenant(context: AuthContext) -> str | None:
    if context.tenant is not None:
        return context.tenant.id
    return None


@billing_router.get("/plans", response_model=list[PlanResponse])
async def list_plans(
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PlanResponse]:
    del context
    rows = await BillingService(session).list_plans()
    return [PlanResponse.model_validate(item) for item in rows]


@billing_router.post(
    "/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED
)
async def create_plan(
    payload: PlanCreate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanResponse:
    del context, csrf_context
    try:
        row = await BillingService(session).create_plan(payload.model_dump())
    except BillingError as error:
        _raise(error)
    return PlanResponse.model_validate(row)


@billing_router.patch("/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: str,
    payload: PlanUpdate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanResponse:
    del context, csrf_context
    try:
        row = await BillingService(session).update_plan(
            plan_id, payload.version, payload.model_dump(exclude={"version"}, exclude_unset=True)
        )
    except BillingError as error:
        _raise(error)
    return PlanResponse.model_validate(row)


@billing_router.get("/subscriptions", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ACCOUNTING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SubscriptionResponse]:
    rows = await BillingService(session).list_subscriptions(_scope_tenant(context))
    return [SubscriptionResponse.model_validate(item) for item in rows]


@billing_router.post(
    "/subscriptions", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED
)
async def create_subscription(
    payload: SubscriptionCreate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriptionResponse:
    del context, csrf_context
    try:
        row = await BillingService(session).subscribe(
            payload.tenant_id,
            payload.plan_id,
            period_start=payload.period_start,
            grace_days=payload.grace_days,
        )
    except BillingError as error:
        _raise(error)
    return SubscriptionResponse.model_validate(row)


@billing_router.patch("/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: str,
    payload: SubscriptionUpdate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriptionResponse:
    del context, csrf_context
    try:
        row = await BillingService(session).update_subscription(
            subscription_id,
            payload.version,
            payload.model_dump(exclude={"version"}, exclude_unset=True),
        )
    except BillingError as error:
        _raise(error)
    return SubscriptionResponse.model_validate(row)


@billing_router.post(
    "/usage-events", response_model=UsageEventResponse, status_code=status.HTTP_201_CREATED
)
async def create_usage_event(
    payload: UsageEventCreate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UsageEventResponse:
    del context, csrf_context
    row = await BillingService(session).record_usage(payload.model_dump())
    return UsageEventResponse.model_validate(row)


@billing_router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ACCOUNTING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[InvoiceResponse]:
    rows = await BillingService(session).list_invoices(_scope_tenant(context))
    return [InvoiceResponse.model_validate(item) for item in rows]


@billing_router.post(
    "/invoices", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED
)
async def generate_invoice(
    payload: InvoiceGenerate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InvoiceResponse:
    del context, csrf_context
    try:
        row = await BillingService(session).generate_invoice(
            payload.tenant_id,
            payload.period_start,
            payload.period_end,
            due_at=payload.due_at,
            description=payload.description,
            amount=payload.amount,
        )
    except BillingError as error:
        _raise(error)
    return InvoiceResponse.model_validate(row)


@billing_router.get("/invoices/{invoice_id}/items", response_model=list[InvoiceItemResponse])
async def list_invoice_items(
    invoice_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ACCOUNTING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[InvoiceItemResponse]:
    del context
    try:
        items = await BillingService(session).list_invoice_items(invoice_id)
    except BillingError as error:
        _raise(error)
    return [InvoiceItemResponse.model_validate(item) for item in items]


@billing_router.post(
    "/invoices/{invoice_id}/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_payment(
    invoice_id: str,
    payload: PaymentCreate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentResponse:
    del csrf_context
    try:
        row = await BillingService(session).record_payment(
            invoice_id,
            amount=payload.amount,
            method=payload.method,
            reference=payload.reference,
            received_at=payload.received_at,
            actor_user_id=context.user.id,
        )
    except BillingError as error:
        _raise(error)
    return PaymentResponse.model_validate(row)


@billing_router.post(
    "/invoices/{invoice_id}/adjustments",
    response_model=AdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_adjustment(
    invoice_id: str,
    payload: AdjustmentCreate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdjustmentResponse:
    del csrf_context
    try:
        row = await BillingService(session).record_adjustment(
            invoice_id,
            kind=payload.kind,
            amount=payload.amount,
            reason=payload.reason,
            actor_user_id=context.user.id,
        )
    except BillingError as error:
        _raise(error)
    return AdjustmentResponse.model_validate(row)


@billing_router.get("/adjustments", response_model=list[AdjustmentResponse])
async def list_adjustments(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ACCOUNTING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AdjustmentResponse]:
    rows = await BillingService(session).list_adjustments(_scope_tenant(context))
    return [AdjustmentResponse.model_validate(item) for item in rows]


@billing_router.get("/summary", response_model=BillingSummaryResponse)
async def billing_summary(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ACCOUNTING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BillingSummaryResponse:
    tenant_id = _scope_tenant(context)
    if tenant_id is None:
        raise auth_error("tenant_required", "请先选择租户", 400)
    service = BillingService(session)
    subscription = await service.get_subscription(tenant_id)
    plan = None
    if subscription is not None:
        plan = await service.get_plan(subscription.plan_id)
    blockers = await service.subscription_blockers(tenant_id)
    return BillingSummaryResponse(
        subscription=SubscriptionResponse.model_validate(subscription) if subscription else None,
        plan=PlanResponse.model_validate(plan) if plan else None,
        outstanding_amount=await service.outstanding_amount(tenant_id),
        blocked=bool(blockers),
        blockers=blockers,
    )


__all__ = ["billing_router"]
