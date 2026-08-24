from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    actor_user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    before_summary: dict[str, Any] | None
    after_summary: dict[str, Any] | None
    correlation_id: str | None
    created_at: datetime


__all__ = ["AuditResponse"]
