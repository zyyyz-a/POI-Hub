from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, require_permission
from poi_admin.core.permissions import Permission

from .schemas import AuditResponse
from .service import AuditService

audit_router = APIRouter(prefix="/audit-logs", tags=["audit"])


@audit_router.get("", response_model=list[AuditResponse])
async def list_audit_logs(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_AUDIT))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AuditResponse]:
    if context.tenant is None:
        from poi_admin.core.dependencies import auth_error

        raise auth_error("tenant_required", "请先选择租户", 400)
    rows = await AuditService(session).list_for_tenant(context.tenant.id)
    return [AuditResponse.model_validate(row) for row in rows]


__all__ = ["audit_router"]
