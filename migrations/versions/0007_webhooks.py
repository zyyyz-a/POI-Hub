"""Durable encrypted callback inbox records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_webhooks"
down_revision: str | None = "0006_local_life_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["wechat_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "fingerprint", name="uq_webhook_connection_fingerprint"
        ),
    )
    op.create_index("ix_webhook_events_tenant_id", "webhook_events", ["tenant_id"])
    op.create_index("ix_webhook_events_connection_id", "webhook_events", ["connection_id"])
    op.create_index("ix_webhook_tenant_received", "webhook_events", ["tenant_id", "received_at"])


def downgrade() -> None:
    op.drop_index("ix_webhook_tenant_received", table_name="webhook_events")
    op.drop_index("ix_webhook_events_connection_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_tenant_id", table_name="webhook_events")
    op.drop_table("webhook_events")
