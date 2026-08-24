"""Local Life orders, vouchers, after-sales, and accounting mirrors."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_local_life_orders"
down_revision: str | None = "0005_local_life_products"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_connection_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "local_orders",
        *_tenant_connection_columns(),
        sa.Column("external_order_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("paid_amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column("customer_reference_masked", sa.String(length=160), nullable=True),
        sa.Column("raw_summary", sa.JSON(), nullable=False),
        sa.Column("raw_checksum", sa.String(length=64), nullable=True),
        sa.Column("remote_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["wechat_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "connection_id", "external_order_id", name="uq_local_order_external_id"
        ),
    )
    op.create_index("ix_local_orders_tenant_id", "local_orders", ["tenant_id"])
    op.create_index("ix_local_orders_connection_id", "local_orders", ["connection_id"])
    op.create_index("ix_local_order_tenant_status", "local_orders", ["tenant_id", "status"])

    op.create_table(
        "local_vouchers",
        *_tenant_connection_columns(),
        sa.Column("order_id", sa.String(length=36), nullable=True),
        sa.Column("external_voucher_id", sa.String(length=160), nullable=False),
        sa.Column("external_product_id", sa.String(length=160), nullable=True),
        sa.Column("external_sku_id", sa.String(length=160), nullable=True),
        sa.Column("code_masked", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consume_store_id", sa.String(length=160), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_summary", sa.JSON(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["wechat_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["local_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "connection_id", "external_voucher_id", name="uq_local_voucher_external_id"
        ),
    )
    op.create_index("ix_local_vouchers_tenant_id", "local_vouchers", ["tenant_id"])
    op.create_index("ix_local_vouchers_connection_id", "local_vouchers", ["connection_id"])
    op.create_index("ix_local_vouchers_order_id", "local_vouchers", ["order_id"])
    op.create_index("ix_local_voucher_tenant_state", "local_vouchers", ["tenant_id", "state"])

    op.create_table(
        "local_after_sales",
        *_tenant_connection_columns(),
        sa.Column("order_id", sa.String(length=36), nullable=True),
        sa.Column("external_after_sale_id", sa.String(length=160), nullable=False),
        sa.Column("after_sale_type", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("refund_amount", sa.Integer(), nullable=False),
        sa.Column("raw_summary", sa.JSON(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["wechat_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["local_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "connection_id",
            "external_after_sale_id",
            name="uq_local_after_sale_external_id",
        ),
    )
    op.create_index("ix_local_after_sales_tenant_id", "local_after_sales", ["tenant_id"])
    op.create_index("ix_local_after_sales_connection_id", "local_after_sales", ["connection_id"])
    op.create_index("ix_local_after_sales_order_id", "local_after_sales", ["order_id"])
    op.create_index(
        "ix_local_after_sale_tenant_status", "local_after_sales", ["tenant_id", "status"]
    )

    for table_name, external_name, index_name in (
        ("local_funds_flows", "external_entry_id", "ix_local_funds_tenant_occurred"),
        ("local_voucher_bills", "external_bill_id", "ix_local_bill_tenant_occurred"),
    ):
        op.create_table(
            table_name,
            *_tenant_connection_columns(),
            sa.Column(external_name, sa.String(length=160), nullable=False),
            sa.Column(
                "entry_type" if table_name == "local_funds_flows" else "bill_type",
                sa.String(length=60),
                nullable=True,
            ),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(length=12), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("raw_summary", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["connection_id"], ["wechat_connections.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "connection_id",
                external_name,
                name=(
                    "uq_local_funds_external_id"
                    if table_name == "local_funds_flows"
                    else "uq_local_bill_external_id"
                ),
            ),
        )
        op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])
        op.create_index(f"ix_{table_name}_connection_id", table_name, ["connection_id"])
        op.create_index(index_name, table_name, ["tenant_id", "occurred_at"])


def downgrade() -> None:
    for table_name in ("local_voucher_bills", "local_funds_flows"):
        op.drop_index(
            f"ix_{table_name}_tenant_occurred"
            if table_name == "local_funds_flows"
            else "ix_local_bill_tenant_occurred",
            table_name=table_name,
        )
        op.drop_index(f"ix_{table_name}_connection_id", table_name=table_name)
        op.drop_index(f"ix_{table_name}_tenant_id", table_name=table_name)
        op.drop_table(table_name)
    op.drop_index("ix_local_after_sale_tenant_status", table_name="local_after_sales")
    op.drop_index("ix_local_after_sales_order_id", table_name="local_after_sales")
    op.drop_index("ix_local_after_sales_connection_id", table_name="local_after_sales")
    op.drop_index("ix_local_after_sales_tenant_id", table_name="local_after_sales")
    op.drop_table("local_after_sales")
    op.drop_index("ix_local_voucher_tenant_state", table_name="local_vouchers")
    op.drop_index("ix_local_vouchers_order_id", table_name="local_vouchers")
    op.drop_index("ix_local_vouchers_connection_id", table_name="local_vouchers")
    op.drop_index("ix_local_vouchers_tenant_id", table_name="local_vouchers")
    op.drop_table("local_vouchers")
    op.drop_index("ix_local_order_tenant_status", table_name="local_orders")
    op.drop_index("ix_local_orders_connection_id", table_name="local_orders")
    op.drop_index("ix_local_orders_tenant_id", table_name="local_orders")
    op.drop_table("local_orders")
