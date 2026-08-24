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
    Text,
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
    product_type: Mapped[str] = mapped_column(String(40), nullable=False, default="group_buying")
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
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class LocalOrder(Base):
    """Tenant-scoped local mirror of a Local Life order."""

    __tablename__ = "local_orders"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "external_order_id", name="uq_local_order_external_id"
        ),
        Index("ix_local_order_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending_sync")
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="CNY")
    customer_reference_masked: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    vouchers: Mapped[list[LocalVoucher]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="LocalVoucher.created_at",
    )
    after_sales: Mapped[list[LocalAfterSale]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="LocalAfterSale.created_at",
    )


class LocalVoucher(Base):
    """Voucher mirror with encrypted operational code and masked presentation."""

    __tablename__ = "local_vouchers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "external_voucher_id", name="uq_local_voucher_external_id"
        ),
        Index("ix_local_voucher_tenant_state", "tenant_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("local_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_voucher_id: Mapped[str] = mapped_column(String(160), nullable=False)
    code_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_product_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    external_sku_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    code_masked: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="available")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consume_store_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_consume_request_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    order: Mapped[LocalOrder | None] = relationship(back_populates="vouchers")


class LocalAfterSale(Base):
    """Tenant-scoped after-sale mirror."""

    __tablename__ = "local_after_sales"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connection_id",
            "external_after_sale_id",
            name="uq_local_after_sale_external_id",
        ),
        Index("ix_local_after_sale_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("local_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_after_sale_id: Mapped[str] = mapped_column(String(160), nullable=False)
    after_sale_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending_sync")
    refund_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    order: Mapped[LocalOrder | None] = relationship(back_populates="after_sales")


class FundsFlow(Base):
    """Immutable-ish synchronized funds-flow entry."""

    __tablename__ = "local_funds_flows"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "external_entry_id", name="uq_local_funds_external_id"
        ),
        Index("ix_local_funds_tenant_occurred", "tenant_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_entry_id: Mapped[str] = mapped_column(String(160), nullable=False)
    entry_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="CNY")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class VoucherBill(Base):
    """Immutable-ish synchronized voucher bill entry."""

    __tablename__ = "local_voucher_bills"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "external_bill_id", name="uq_local_bill_external_id"
        ),
        Index("ix_local_bill_tenant_occurred", "tenant_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_bill_id: Mapped[str] = mapped_column(String(160), nullable=False)
    bill_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="CNY")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


# Short aliases keep the public domain vocabulary convenient for callers.
Voucher = LocalVoucher
AfterSale = LocalAfterSale
Order = LocalOrder
LocalFundsFlow = FundsFlow
LocalVoucherBill = VoucherBill


__all__ = [
    "AfterSale",
    "FundsFlow",
    "LocalAfterSale",
    "LocalFundsFlow",
    "LocalOrder",
    "LocalProduct",
    "LocalSku",
    "LocalVoucher",
    "LocalVoucherBill",
    "Order",
    "ProductStatus",
    "Voucher",
    "VoucherBill",
    "new_id",
    "utcnow",
]
