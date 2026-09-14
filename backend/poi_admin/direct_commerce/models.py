"""Tenant-scoped products, consumers, orders, appointments, and vouchers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from poi_admin.core.orm import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class DirectProduct(Base):
    __tablename__ = "direct_products"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "mini_program_id", "merchant_product_id", name="uq_direct_product_merchant"
        ),
        CheckConstraint("sale_price > 0", name="ck_direct_product_sale_price"),
        CheckConstraint("market_price > 0", name="ck_direct_product_market_price"),
        CheckConstraint("stock >= 0", name="ck_direct_product_stock"),
        Index("ix_direct_product_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mini_program_id: Mapped[str] = mapped_column(
        ForeignKey("merchant_mini_programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    merchant_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sale_price: Mapped[int] = mapped_column(Integer, nullable=False)
    market_price: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sold_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    appointment_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    service_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ConsumerIdentity(Base):
    __tablename__ = "consumer_identities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "mini_program_id", "openid_hash", name="uq_consumer_openid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mini_program_id: Mapped[str] = mapped_column(
        ForeignKey("merchant_mini_programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    openid_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    openid_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ConsumerSession(Base):
    __tablename__ = "consumer_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("consumer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class MerchantPaymentProfile(Base):
    """Per-store payment routing profile selected by the server, never the client."""

    __tablename__ = "merchant_payment_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", name="uq_payment_profile_store"),
        Index("ix_payment_profile_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("wechat_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="ordinary")
    mchid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sub_mchid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sp_mchid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class PlatformConsumerIdentity(Base):
    """Consumer identity scoped to the platform AppID, not to one merchant."""

    __tablename__ = "platform_consumer_identities"
    __table_args__ = (
        UniqueConstraint(
            "platform_mini_program_id", "openid_hash", name="uq_platform_consumer_openid"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    platform_mini_program_id: Mapped[str] = mapped_column(
        ForeignKey("platform_mini_programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    openid_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    openid_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class PlatformConsumerSession(Base):
    __tablename__ = "platform_consumer_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("platform_consumer_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class DirectOrder(Base):
    __tablename__ = "direct_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_no", name="uq_direct_order_no"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_direct_order_idempotency"),
        CheckConstraint("quantity = 1", name="ck_direct_order_quantity"),
        CheckConstraint("total_amount > 0", name="ck_direct_order_amount"),
        Index("ix_direct_order_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mini_program_id: Mapped[str] = mapped_column(
        ForeignKey("merchant_mini_programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("direct_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    consumer_id: Mapped[str | None] = mapped_column(
        ForeignKey("consumer_identities.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    platform_mini_program_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_mini_programs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    store_binding_id: Mapped[str | None] = mapped_column(
        ForeignKey("mini_program_store_bindings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    platform_consumer_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_consumer_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payment_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("merchant_payment_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    store_code_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mchid_snapshot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sub_mchid_snapshot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refunded_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="payment_pending")
    prepay_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class DirectVoucher(Base):
    __tablename__ = "direct_vouchers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code_hash", name="uq_direct_voucher_code"),
        Index("ix_direct_voucher_tenant_state", "tenant_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("direct_orders.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    code_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="available")
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consume_store_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    consumed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class DirectAppointment(Base):
    __tablename__ = "direct_appointments"
    __table_args__ = (Index("ix_direct_appointment_store_time", "store_id", "starts_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("direct_orders.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(80), nullable=False)
    contact_phone_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    contact_phone_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="confirmed")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class DirectRefund(Base):
    __tablename__ = "direct_refunds"
    __table_args__ = (
        UniqueConstraint("tenant_id", "refund_no", name="uq_direct_refund_no"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_direct_refund_idempotency"),
        CheckConstraint("amount > 0", name="ck_direct_refund_amount"),
        Index("ix_direct_refund_tenant_status", "tenant_id", "status"),
        Index("ix_direct_refund_order", "order_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("direct_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payment_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("merchant_payment_profiles.id", ondelete="SET NULL"), nullable=True
    )
    refund_no: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    transaction_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    wechat_refund_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


__all__ = [
    "ConsumerIdentity",
    "ConsumerSession",
    "DirectAppointment",
    "DirectOrder",
    "DirectProduct",
    "DirectRefund",
    "DirectVoucher",
    "MerchantPaymentProfile",
    "PlatformConsumerIdentity",
    "PlatformConsumerSession",
    "new_id",
    "utcnow",
]
