"""Tenant-scoped onboarding and WeChat position-service records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from poi_admin.core.orm import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class MerchantOnboardingCase(Base):
    """One merchant/store attempt through an official WeChat capability route."""

    __tablename__ = "merchant_onboarding_cases"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "store_id", "route", "category_code", name="uq_onboarding_route"
        ),
        Index("ix_onboarding_tenant_stage", "tenant_id", "stage"),
        Index("ix_onboarding_tenant_official", "tenant_id", "official_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    route: Mapped[str] = mapped_column(
        String(50), nullable=False, default="wechat_location_miniprogram"
    )
    category_code: Mapped[str] = mapped_column(String(100), nullable=False)
    category_name: Mapped[str] = mapped_column(String(160), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    region_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="precheck")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="in_progress")
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    precheck_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    precheck_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    official_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="not_submitted"
    )
    official_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    official_evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    official_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    official_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    position_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_started")
    blocker_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    blocker_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class MerchantMiniProgram(Base):
    """Merchant-owned or platform-owned consumer mini-program registration."""

    __tablename__ = "merchant_mini_programs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "app_id", name="uq_mini_program_tenant_appid"),
        Index("ix_mini_program_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    app_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    ownership_mode: Mapped[str] = mapped_column(
        String(40), nullable=False, default="merchant_owned"
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    authorization_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payment_merchant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payment_owner_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    video_channel_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location_service_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="not_configured"
    )
    callback_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class PositionServiceMount(Base):
    """A mini-program service definition authorized and mounted on a WeChat POI."""

    __tablename__ = "position_service_mounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "store_id",
            "mini_program_id",
            "service_type",
            name="uq_position_service_mount",
        ),
        Index("ix_position_mount_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    onboarding_case_id: Mapped[str] = mapped_column(
        ForeignKey("merchant_onboarding_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_poi_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_pois.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mini_program_id: Mapped[str] = mapped_column(
        ForeignKey("merchant_mini_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_type: Mapped[str] = mapped_column(String(50), nullable=False)
    service_name: Mapped[str] = mapped_column(String(80), nullable=False)
    entry_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    official_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mounted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


__all__ = ["MerchantMiniProgram", "MerchantOnboardingCase", "PositionServiceMount"]
