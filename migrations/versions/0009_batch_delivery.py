"""Leased webhook delivery and bounded retry metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_batch_delivery"
down_revision: str | None = "0008_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.add_column(
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8")
        )
        batch_op.add_column(sa.Column("worker_id", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.execute("UPDATE webhook_events SET next_attempt_at = received_at")
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.alter_column("next_attempt_at", nullable=False)
        batch_op.create_index("ix_webhook_claimable", ["status", "next_attempt_at"])


def downgrade() -> None:
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.drop_index("ix_webhook_claimable")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("worker_id")
        batch_op.drop_column("max_attempts")
