"""Encrypted, tenant-scoped application drafts and private attachments."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from poi_admin.core.orm import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class MerchantApplyment(Base):
    __tablename__ = "merchant_applyments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", name="uq_merchant_applyment_store"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    connection_id: Mapped[str] = mapped_column(ForeignKey("wechat_connections.id"))
    business_code: Mapped[str] = mapped_column(String(124), unique=True)
    sp_mchid: Mapped[str] = mapped_column(String(32))
    platform_app_id: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(50), default="draft")
    encrypted_fields: Mapped[str] = mapped_column(Text)
    encrypted_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    applyment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sub_mchid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorized_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApplymentAttachment(Base):
    __tablename__ = "merchant_applyment_attachments"
    __table_args__ = (
        UniqueConstraint("applyment_id", "kind", name="uq_applyment_attachment_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    applyment_id: Mapped[str] = mapped_column(
        ForeignKey("merchant_applyments.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    encrypted_content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
