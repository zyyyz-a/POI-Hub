"""Local Life products, SKU identifiers, and synchronized inventory."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_local_life_products"
down_revision: str | None = "0004_stores_pois"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "local_products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("external_product_id", sa.String(length=160), nullable=True),
        sa.Column("merchant_product_id", sa.String(length=128), nullable=False),
        sa.Column("product_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=160), nullable=True),
        sa.Column("brand", sa.String(length=160), nullable=True),
        sa.Column("head_images", sa.JSON(), nullable=False),
        sa.Column("available_store_desc", sa.String(length=1000), nullable=True),
        sa.Column("verification_settings", sa.JSON(), nullable=False),
        sa.Column("code_source", sa.String(length=30), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("remote_status", sa.String(length=30), nullable=False),
        sa.Column("desired_state", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["wechat_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "connection_id",
            "external_product_id",
            name="uq_local_product_external_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "connection_id",
            "merchant_product_id",
            name="uq_local_product_merchant_id",
        ),
    )
    op.create_index("ix_local_products_tenant_id", "local_products", ["tenant_id"])
    op.create_index("ix_local_products_connection_id", "local_products", ["connection_id"])
    op.create_index(
        "ix_local_product_tenant_status",
        "local_products",
        ["tenant_id", "remote_status"],
    )

    op.create_table(
        "local_skus",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("external_sku_id", sa.String(length=160), nullable=True),
        sa.Column("merchant_sku_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("sale_price", sa.Integer(), nullable=False),
        sa.Column("market_price", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("desired_stock", sa.Integer(), nullable=False),
        sa.Column("sold_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_stock_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "desired_stock >= 0", name="ck_local_sku_desired_stock_nonnegative"
        ),
        sa.CheckConstraint(
            "market_price > 0", name="ck_local_sku_market_price_positive"
        ),
        sa.CheckConstraint("sale_price > 0", name="ck_local_sku_sale_price_positive"),
        sa.CheckConstraint("stock >= 0", name="ck_local_sku_stock_nonnegative"),
        sa.ForeignKeyConstraint(
            ["product_id"], ["local_products.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "external_sku_id",
            name="uq_local_sku_external_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "merchant_sku_id",
            name="uq_local_sku_merchant_id",
        ),
    )
    op.create_index("ix_local_skus_tenant_id", "local_skus", ["tenant_id"])
    op.create_index("ix_local_skus_product_id", "local_skus", ["product_id"])
    op.create_index(
        "ix_local_sku_tenant_product", "local_skus", ["tenant_id", "product_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_local_sku_tenant_product", table_name="local_skus")
    op.drop_index("ix_local_skus_product_id", table_name="local_skus")
    op.drop_index("ix_local_skus_tenant_id", table_name="local_skus")
    op.drop_table("local_skus")
    op.drop_index("ix_local_product_tenant_status", table_name="local_products")
    op.drop_index("ix_local_products_connection_id", table_name="local_products")
    op.drop_index("ix_local_products_tenant_id", table_name="local_products")
    op.drop_table("local_products")
