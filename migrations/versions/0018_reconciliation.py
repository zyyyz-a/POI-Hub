"""WeChat Pay trade-bill reconciliation batches and items."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_reconciliation"
down_revision: str | None = "0017_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "direct_reconciliation_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("bill_date", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("statement_total", sa.Integer(), nullable=False),
        sa.Column("platform_total", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("difference_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "bill_date", name="uq_direct_recon_batch"
        ),
    )
    op.create_index(
        "ix_direct_reconciliation_batches_tenant_id",
        "direct_reconciliation_batches",
        ["tenant_id"],
    )
    op.create_index(
        "ix_direct_recon_batch_tenant_status",
        "direct_reconciliation_batches",
        ["tenant_id", "status"],
    )

    op.create_table(
        "direct_reconciliation_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("order_no", sa.String(length=64), nullable=True),
        sa.Column("transaction_id", sa.String(length=160), nullable=True),
        sa.Column("statement_amount", sa.Integer(), nullable=True),
        sa.Column("platform_amount", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("resolved_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["direct_reconciliation_batches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_direct_reconciliation_items_batch_id",
        "direct_reconciliation_items",
        ["batch_id"],
    )
    op.create_index(
        "ix_direct_reconciliation_items_tenant_id",
        "direct_reconciliation_items",
        ["tenant_id"],
    )
    op.create_index("ix_direct_recon_item_batch", "direct_reconciliation_items", ["batch_id"])


def downgrade() -> None:
    op.drop_table("direct_reconciliation_items")
    op.drop_table("direct_reconciliation_batches")
