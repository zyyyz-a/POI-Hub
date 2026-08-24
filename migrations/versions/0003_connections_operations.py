"""Tenant connections and durable integration operations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_connections_operations"
down_revision: str | None = "0002_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wechat_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=30), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("mock_scenario", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("encrypted_secrets", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permission_snapshot", sa.JSON(), nullable=True),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "capability", name="uq_connection_tenant_capability"),
    )
    op.create_index("ix_wechat_connections_tenant_id", "wechat_connections", ["tenant_id"])
    op.create_index("ix_connection_tenant_status", "wechat_connections", ["tenant_id", "status"])
    op.create_table(
        "integration_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("command_type", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("resource_ref", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("response_summary", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["wechat_connections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_operation_tenant_idempotency"),
    )
    op.create_index("ix_integration_operations_tenant_id", "integration_operations", ["tenant_id"])
    op.create_index(
        "ix_integration_operations_connection_id", "integration_operations", ["connection_id"]
    )
    op.create_index(
        "ix_operation_claimable", "integration_operations", ["status", "next_attempt_at"]
    )
    op.create_index(
        "ix_operation_tenant_created", "integration_operations", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_operation_tenant_created", table_name="integration_operations")
    op.drop_index("ix_operation_claimable", table_name="integration_operations")
    op.drop_index("ix_integration_operations_connection_id", table_name="integration_operations")
    op.drop_index("ix_integration_operations_tenant_id", table_name="integration_operations")
    op.drop_table("integration_operations")
    op.drop_index("ix_connection_tenant_status", table_name="wechat_connections")
    op.drop_index("ix_wechat_connections_tenant_id", table_name="wechat_connections")
    op.drop_table("wechat_connections")
