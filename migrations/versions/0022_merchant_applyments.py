"""Encrypted individual-business applyment drafts and private images."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_merchant_applyments"
down_revision: str | None = "0021_platform_products"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "merchant_applyments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column(
            "connection_id", sa.String(36), sa.ForeignKey("wechat_connections.id"), nullable=False
        ),
        sa.Column("business_code", sa.String(124), nullable=False, unique=True),
        sa.Column("sp_mchid", sa.String(32), nullable=False),
        sa.Column("platform_app_id", sa.String(32), nullable=False),
        sa.Column("state", sa.String(50), nullable=False),
        sa.Column("encrypted_fields", sa.Text(), nullable=False),
        sa.Column("encrypted_result", sa.Text(), nullable=True),
        sa.Column("applyment_id", sa.String(64), nullable=True),
        sa.Column("sub_mchid", sa.String(32), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("last_request_id", sa.String(160), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorized_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "store_id", name="uq_merchant_applyment_store"),
    )
    op.create_index("ix_merchant_applyments_tenant_id", "merchant_applyments", ["tenant_id"])
    op.create_table(
        "merchant_applyment_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "applyment_id",
            sa.String(36),
            sa.ForeignKey("merchant_applyments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("applyment_id", "kind", name="uq_applyment_attachment_kind"),
    )
    op.create_index(
        "ix_merchant_applyment_attachments_applyment_id",
        "merchant_applyment_attachments",
        ["applyment_id"],
    )


def downgrade() -> None:
    op.drop_table("merchant_applyment_attachments")
    op.drop_table("merchant_applyments")
