from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.crypto import redact_secrets

from .models import AuditLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        tenant_id: str,
        actor_user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> AuditLog:
        row = AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_summary=redact_secrets(before) if before is not None else None,
            after_summary=redact_secrets(after) if after is not None else None,
            correlation_id=correlation_id,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_for_tenant(self, tenant_id: str, *, limit: int = 100) -> list[AuditLog]:
        rows = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(min(max(limit, 1), 500))
        )
        return list(rows.scalars().all())


__all__ = ["AuditService"]
