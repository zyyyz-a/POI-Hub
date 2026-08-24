from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class BatchRetryRequest(BaseModel):
    operation_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("operation_ids")
    @classmethod
    def validate_operation_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("operation_ids must not contain empty values")
        return list(dict.fromkeys(normalized))


class BatchRetryItemResponse(BaseModel):
    operation_id: str
    accepted: bool
    reason: str | None = None


class BatchRetryResponse(BaseModel):
    accepted_count: int
    rejected_count: int
    items: list[BatchRetryItemResponse]
