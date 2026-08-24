"""Tenant-owned stores, remote POI mirrors, candidates, and mapping history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from poi_admin.core.orm import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_store_tenant_code"),
        Index("ix_store_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_phone_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    province: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ServicePoi(Base):
    __tablename__ = "service_pois"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "external_poi_id", name="uq_poi_remote_id"
        ),
        Index("ix_poi_tenant_connection", "tenant_id", "connection_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_poi_id: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    remote_status: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    qualification_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class MatchCandidate(Base):
    __tablename__ = "match_candidates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "store_id", "service_poi_id", name="uq_candidate_store_poi"
        ),
        Index("ix_candidate_tenant_score", "tenant_id", "total_score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_poi_id: Mapped[str] = mapped_column(
        ForeignKey("service_pois.id", ondelete="CASCADE"), nullable=False, index=True
    )
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    name_score: Mapped[float] = mapped_column(Float, nullable=False)
    address_score: Mapped[float] = mapped_column(Float, nullable=False)
    distance_score: Mapped[float] = mapped_column(Float, nullable=False)
    distance_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class StorePoiMapping(Base):
    __tablename__ = "store_poi_mappings"
    __table_args__ = (
        Index(
            "uq_active_mapping_store",
            "tenant_id",
            "connection_id",
            "store_id",
            unique=True,
            sqlite_where=text("state = 'active'"),
            postgresql_where=text("state = 'active'"),
        ),
        Index(
            "uq_active_mapping_poi",
            "tenant_id",
            "connection_id",
            "service_poi_id",
            unique=True,
            sqlite_where=text("state = 'active'"),
            postgresql_where=text("state = 'active'"),
        ),
        Index("ix_mapping_tenant_state", "tenant_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_poi_id: Mapped[str] = mapped_column(
        ForeignKey("service_pois.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confirmed_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    unbound_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "MatchCandidate",
    "ServicePoi",
    "Store",
    "StorePoiMapping",
    "new_id",
    "utcnow",
]
