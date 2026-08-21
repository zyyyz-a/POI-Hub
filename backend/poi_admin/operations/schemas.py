from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from .models import OperationStatus


class OperationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str | None
    command_type: str
    resource_ref: str | None
    status: OperationStatus
    attempt_count: int
    max_attempts: int
    response_summary: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    next_attempt_at: datetime
    created_at: datetime
    completed_at: datetime | None
