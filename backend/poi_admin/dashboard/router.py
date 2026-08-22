"""Tenant-scoped operational dashboard summary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, require_tenant_permission
from poi_admin.core.permissions import Permission
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
    return DashboardResponse(
        summary=DashboardSummary(
            pending_audits=0,
            failed_operations=int(failed_operations or 0),
            low_stock=0,
            unmapped_stores=int(unmapped_stores or 0),
        )
    )


__all__ = ["dashboard_router"]
