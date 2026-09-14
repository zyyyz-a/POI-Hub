"""Idempotent refunds and order refunded amount."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_direct_refunds"
down_revision: str | None = "0015_single_quantity_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "direct_refunds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("payment_profile_id", sa.String(length=36), nullable=True),
        sa.Column("refund_no", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("transaction_id", sa.String(length=160), nullable=True),
        sa.Column("wechat_refund_id", sa.String(length=160), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_direct_refund_amount"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["order_id"], ["direct_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["payment_profile_id"], ["merchant_payment_profiles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "refund_no", name="uq_direct_refund_no"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_direct_refund_idempotency"
        ),
    )
    for column in ("tenant_id", "order_id", "store_id"):
        op.create_index(f"ix_direct_refunds_{column}", "direct_refunds", [column])
    op.create_index(
        "ix_direct_refund_tenant_status", "direct_refunds", ["tenant_id", "status"]
    )
    op.create_index("ix_direct_refund_order", "direct_refunds", ["order_id"])

    op.add_column(
        "direct_orders",
        sa.Column(
            "refunded_amount", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("direct_orders", "refunded_amount")
    op.drop_table("direct_refunds")
