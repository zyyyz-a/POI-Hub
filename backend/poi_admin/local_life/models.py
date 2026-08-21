"""Tenant-scoped Local Life products and SKU inventory."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from poi_admin.core.orm import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class ProductStatus(StrEnum):
    PENDING_CREATE = "pending_create"
    UNDER_REVIEW = "under_review"
    DRAFT = "draft"
    APPROVED = "approved"
    LISTED = "listed"
    DELISTED = "delisted"
    DELETED = "deleted"


class LocalProduct(Base):
    __tablename__ = "local_products"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connection_id",
            "merchant_product_id",
            name="uq_local_product_merchant_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "connection_id",
            "external_product_id",
            name="uq_local_product_external_id",
        ),
        Index("ix_local_product_tenant_status", "tenant_id", "remote_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_product_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    merchant_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="group_buying"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(160), nullable=True)
    head_images: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    available_store_desc: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    verification_settings: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    code_source: Mapped[str] = mapped_column(String(30), nullable=False, default="wechat")
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    remote_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ProductStatus.PENDING_CREATE.value
    )
    desired_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ProductStatus.UNDER_REVIEW.value
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    skus: Mapped[list[LocalSku]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="LocalSku.created_at",
    )


class LocalSku(Base):
    __tablename__ = "local_skus"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "product_id", "merchant_sku_id", name="uq_local_sku_merchant_id"
        ),
        UniqueConstraint(
            "tenant_id", "product_id", "external_sku_id", name="uq_local_sku_external_id"
        ),
        CheckConstraint("sale_price > 0", name="ck_local_sku_sale_price_positive"),
        CheckConstraint("market_price > 0", name="ck_local_sku_market_price_positive"),
        CheckConstraint("stock >= 0", name="ck_local_sku_stock_nonnegative"),
        CheckConstraint("desired_stock >= 0", name="ck_local_sku_desired_stock_nonnegative"),
        Index("ix_local_sku_tenant_product", "tenant_id", "product_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("local_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_sku_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    merchant_sku_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sale_price: Mapped[int] = mapped_column(Integer, nullable=False)
    market_price: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    desired_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sold_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_stock_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    product: Mapped[LocalProduct] = relationship(back_populates="skus")


__all__ = ["LocalProduct", "LocalSku", "ProductStatus", "new_id", "utcnow"]
