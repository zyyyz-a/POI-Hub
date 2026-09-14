"""Platform mini-program, store entry bindings, and per-store payment profiles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_platform_mini_programs"
down_revision: str | None = "0012_direct_commerce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_mini_programs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=True),
        sa.Column("owner_subject", sa.String(length=200), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("callback_configured", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["wechat_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", name="uq_platform_app_id"),
    )
    op.create_index(
        "ix_platform_mini_programs_connection_id",
        "platform_mini_programs",
        ["connection_id"],
    )
    op.create_index(
        "ix_platform_mini_program_status", "platform_mini_programs", ["status"]
    )

    op.create_table(
        "mini_program_store_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("platform_mini_program_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("store_code", sa.String(length=64), nullable=False),
        sa.Column("tencent_poi_id", sa.String(length=160), nullable=True),
        sa.Column("entry_path", sa.String(length=500), nullable=True),
        sa.Column("entry_scene", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("official_reference", sa.String(length=200), nullable=True),
        sa.Column("evidence_reference", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["platform_mini_program_id"],
            ["platform_mini_programs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_code", name="uq_binding_store_code"),
        sa.UniqueConstraint(
            "platform_mini_program_id", "store_id", name="uq_binding_program_store"
        ),
    )
    for column in ("platform_mini_program_id", "tenant_id", "store_id"):
        op.create_index(
            f"ix_mini_program_store_bindings_{column}",
            "mini_program_store_bindings",
            [column],
        )
    op.create_index(
        "ix_binding_tenant_status",
        "mini_program_store_bindings",
        ["tenant_id", "status"],
    )

    op.create_table(
        "merchant_payment_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("mchid", sa.String(length=128), nullable=True),
        sa.Column("sub_mchid", sa.String(length=128), nullable=True),
        sa.Column("sp_mchid", sa.String(length=128), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["wechat_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "store_id", name="uq_payment_profile_store"),
    )
    for column in ("tenant_id", "store_id", "connection_id"):
        op.create_index(
            f"ix_merchant_payment_profiles_{column}",
            "merchant_payment_profiles",
            [column],
        )
    op.create_index(
        "ix_payment_profile_tenant_status",
        "merchant_payment_profiles",
        ["tenant_id", "status"],
    )

    op.create_table(
        "platform_consumer_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("platform_mini_program_id", sa.String(length=36), nullable=False),
        sa.Column("openid_hash", sa.String(length=64), nullable=False),
        sa.Column("openid_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["platform_mini_program_id"],
            ["platform_mini_programs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform_mini_program_id",
            "openid_hash",
            name="uq_platform_consumer_openid",
        ),
    )
    op.create_index(
        "ix_platform_consumer_identities_platform_mini_program_id",
        "platform_consumer_identities",
        ["platform_mini_program_id"],
    )

    op.create_table(
        "platform_consumer_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identity_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["identity_id"], ["platform_consumer_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_consumer_sessions_identity_id",
        "platform_consumer_sessions",
        ["identity_id"],
    )
    op.create_index(
        "ix_platform_consumer_sessions_token_hash",
        "platform_consumer_sessions",
        ["token_hash"],
        unique=True,
    )

    op.add_column(
        "direct_orders",
        sa.Column("platform_mini_program_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "direct_orders",
        sa.Column("store_binding_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "direct_orders",
        sa.Column("platform_consumer_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "direct_orders",
        sa.Column("payment_profile_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "direct_orders",
        sa.Column("store_code_snapshot", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "direct_orders",
        sa.Column("payment_mode", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "direct_orders",
        sa.Column("mchid_snapshot", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "direct_orders",
        sa.Column("sub_mchid_snapshot", sa.String(length=128), nullable=True),
    )
    for column in (
        "platform_mini_program_id",
        "store_binding_id",
        "platform_consumer_id",
        "payment_profile_id",
    ):
        op.create_index(f"ix_direct_orders_{column}", "direct_orders", [column])


def downgrade() -> None:
    for column in (
        "platform_mini_program_id",
        "store_binding_id",
        "platform_consumer_id",
        "payment_profile_id",
    ):
        op.drop_index(f"ix_direct_orders_{column}", table_name="direct_orders")
    for column in (
        "sub_mchid_snapshot",
        "mchid_snapshot",
        "payment_mode",
        "store_code_snapshot",
        "payment_profile_id",
        "platform_consumer_id",
        "store_binding_id",
        "platform_mini_program_id",
    ):
        op.drop_column("direct_orders", column)
    op.drop_table("platform_consumer_sessions")
    op.drop_table("platform_consumer_identities")
    op.drop_table("merchant_payment_profiles")
    op.drop_table("mini_program_store_bindings")
    op.drop_table("platform_mini_programs")
