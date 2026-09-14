"""Merchant-owned mini-program products, payments, appointments, and vouchers."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_direct_commerce"
down_revision: str | None = "0011_position_onboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "direct_products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("mini_program_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("merchant_product_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cover_image", sa.String(length=500), nullable=True),
        sa.Column("sale_price", sa.Integer(), nullable=False),
        sa.Column("market_price", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("sold_count", sa.Integer(), nullable=False),
        sa.Column("appointment_required", sa.Boolean(), nullable=False),
        sa.Column("service_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market_price > 0", name="ck_direct_product_market_price"),
        sa.CheckConstraint("sale_price > 0", name="ck_direct_product_sale_price"),
        sa.CheckConstraint("stock >= 0", name="ck_direct_product_stock"),
        sa.ForeignKeyConstraint(
            ["mini_program_id"], ["merchant_mini_programs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "mini_program_id", "merchant_product_id", name="uq_direct_product_merchant"
        ),
    )
    for column in ("tenant_id", "mini_program_id", "store_id"):
        op.create_index(f"ix_direct_products_{column}", "direct_products", [column])
    op.create_index("ix_direct_product_tenant_status", "direct_products", ["tenant_id", "status"])

    op.create_table(
        "consumer_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("mini_program_id", sa.String(length=36), nullable=False),
        sa.Column("openid_hash", sa.String(length=64), nullable=False),
        sa.Column("openid_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["mini_program_id"], ["merchant_mini_programs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "mini_program_id", "openid_hash", name="uq_consumer_openid"
        ),
    )
    op.create_index("ix_consumer_identities_tenant_id", "consumer_identities", ["tenant_id"])
    op.create_index(
        "ix_consumer_identities_mini_program_id", "consumer_identities", ["mini_program_id"]
    )

    op.create_table(
        "consumer_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identity_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["consumer_identities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consumer_sessions_identity_id", "consumer_sessions", ["identity_id"])
    op.create_index(
        "ix_consumer_sessions_token_hash", "consumer_sessions", ["token_hash"], unique=True
    )

    op.create_table(
        "direct_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("mini_program_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("consumer_id", sa.String(length=36), nullable=False),
        sa.Column("order_no", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_amount", sa.Integer(), nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("paid_amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("prepay_id", sa.String(length=160), nullable=True),
        sa.Column("transaction_id", sa.String(length=160), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_direct_order_quantity"),
        sa.CheckConstraint("total_amount > 0", name="ck_direct_order_amount"),
        sa.ForeignKeyConstraint(["consumer_id"], ["consumer_identities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["mini_program_id"], ["merchant_mini_programs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["direct_products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_direct_order_idempotency"),
        sa.UniqueConstraint("tenant_id", "order_no", name="uq_direct_order_no"),
        sa.UniqueConstraint("transaction_id"),
    )
    for column in ("tenant_id", "mini_program_id", "store_id", "product_id", "consumer_id"):
        op.create_index(f"ix_direct_orders_{column}", "direct_orders", [column])
    op.create_index("ix_direct_order_tenant_status", "direct_orders", ["tenant_id", "status"])

    op.create_table(
        "direct_vouchers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("code_ciphertext", sa.Text(), nullable=False),
        sa.Column("code_masked", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consume_store_id", sa.String(length=36), nullable=True),
        sa.Column("consumed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["consumed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["order_id"], ["direct_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
        sa.UniqueConstraint("tenant_id", "code_hash", name="uq_direct_voucher_code"),
    )
    op.create_index("ix_direct_vouchers_tenant_id", "direct_vouchers", ["tenant_id"])
    op.create_index("ix_direct_vouchers_order_id", "direct_vouchers", ["order_id"], unique=True)
    op.create_index("ix_direct_voucher_tenant_state", "direct_vouchers", ["tenant_id", "state"])

    op.create_table(
        "direct_appointments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contact_name", sa.String(length=80), nullable=False),
        sa.Column("contact_phone_ciphertext", sa.Text(), nullable=False),
        sa.Column("contact_phone_masked", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["direct_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index("ix_direct_appointments_tenant_id", "direct_appointments", ["tenant_id"])
    op.create_index(
        "ix_direct_appointments_order_id", "direct_appointments", ["order_id"], unique=True
    )
    op.create_index("ix_direct_appointments_store_id", "direct_appointments", ["store_id"])
    op.create_index(
        "ix_direct_appointment_store_time", "direct_appointments", ["store_id", "starts_at"]
    )


def downgrade() -> None:
    op.drop_table("direct_appointments")
    op.drop_table("direct_vouchers")
    op.drop_table("direct_orders")
    op.drop_table("consumer_sessions")
    op.drop_table("consumer_identities")
    op.drop_table("direct_products")
