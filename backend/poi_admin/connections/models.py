"""Tenant-scoped WeChat connection persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from poi_admin.core.orm import Base

from .ports import AuthorizationState, ConnectionMode


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class WeChatConnection(Base):
    __tablename__ = "wechat_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "capability", name="uq_connection_tenant_capability"),
        Index("ix_connection_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default=ConnectionMode.MOCK.value)
    mock_scenario: Mapped[str] = mapped_column(String(40), nullable=False, default="healthy")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AuthorizationState.DISCONNECTED.value
    )
    app_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    merchant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    encrypted_secrets: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    permission_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


__all__ = ["WeChatConnection", "new_id", "utcnow"]
