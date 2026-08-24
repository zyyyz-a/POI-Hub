from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .ports import AuthorizationState, Capability, ConnectionMode


class ConnectionCreateRequest(BaseModel):
    capability: Capability
    mode: ConnectionMode = ConnectionMode.MOCK
    app_id: str | None = Field(default=None, max_length=128)
    merchant_id: str | None = Field(default=None, max_length=128)
    secrets: dict[str, str] = Field(default_factory=dict)
    mock_scenario: Literal[
        "healthy", "rate_limit", "timeout", "server_error", "invalid", "permission_denied"
    ] = "healthy"


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    capability: Capability
    mode: ConnectionMode
    mock_scenario: str
    status: AuthorizationState
    app_id: str | None
    merchant_id: str | None
    token_expires_at: datetime | None
    permission_snapshot: dict[str, Any] | None
    last_health_check_at: datetime | None
    last_error: str | None


__all__ = ["ConnectionCreateRequest", "ConnectionResponse"]
