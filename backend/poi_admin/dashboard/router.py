"""Tenant-scoped operational dashboard summary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import AuthorizationState
from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, require_tenant_permission
from poi_admin.core.permissions import Permission
from poi_admin.local_life.accounting import AccountingService
from poi_admin.local_life.models import LocalProduct, LocalSku, ProductStatus
from poi_admin.operations.models import IntegrationOperation, OperationStatus
from poi_admin.stores.models import Store, StorePoiMapping

from .schemas import DashboardResponse, DashboardSummary

dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@dashboard_router.get("", response_model=DashboardResponse)
async def dashboard_summary(
    context: Annotated[
        AuthContext, Depends(require_tenant_permission(Permission.VIEW_DASHBOARD))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DashboardResponse:
    """Return aggregate counters for the explicitly selected tenant.

    Audit and product inventory modules are optional in the first release; those
    counters intentionally default to zero until their tables are available.
    """

    tenant_id = context.tenant_id
    if tenant_id is None:
        from poi_admin.core.dependencies import auth_error

        raise auth_error("tenant_required", "请先选择租户", 400)
    failed_operations = await session.scalar(
        select(func.count())
        .select_from(IntegrationOperation)
        .where(
            IntegrationOperation.tenant_id == tenant_id,
            IntegrationOperation.status == OperationStatus.FAILED.value,
        )
    )
    unmapped_stores = await session.scalar(
        select(func.count())
        .select_from(Store)
        .where(
            Store.tenant_id == tenant_id,
            ~select(StorePoiMapping.id)
            .where(
                StorePoiMapping.tenant_id == Store.tenant_id,
                StorePoiMapping.store_id == Store.id,
                StorePoiMapping.state == "active",
            )
            .exists(),
        )
    )
    pending_audits = await session.scalar(
        select(func.count())
        .select_from(LocalProduct)
        .where(
            LocalProduct.tenant_id == tenant_id,
            LocalProduct.remote_status == ProductStatus.UNDER_REVIEW.value,
        )
    )
    low_stock = await session.scalar(
        select(func.count())
        .select_from(LocalSku)
        .where(
            LocalSku.tenant_id == tenant_id,
            LocalSku.stock < LocalSku.desired_stock,
        )
    )
    reconciliation = await AccountingService(session).reconciliation_summary(tenant_id)
    unhealthy_connections = await session.scalar(
        select(func.count())
        .select_from(WeChatConnection)
        .where(
            WeChatConnection.tenant_id == tenant_id,
            WeChatConnection.status != AuthorizationState.AUTHORIZED.value,
        )
    )
    return DashboardResponse(
        summary=DashboardSummary(
            pending_audits=int(pending_audits or 0),
            failed_operations=int(failed_operations or 0),
            low_stock=int(low_stock or 0),
            unmapped_stores=int(unmapped_stores or 0),
            reconciliation_differences=int(reconciliation["difference_count"]),
            unhealthy_connections=int(unhealthy_connections or 0),
        )
    )


__all__ = ["dashboard_router"]
