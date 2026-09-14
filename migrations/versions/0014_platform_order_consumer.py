"""Allow platform orders to omit the tenant-scoped consumer identity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_platform_order_consumer"
down_revision: str | None = "0013_platform_mini_programs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("direct_orders") as batch_op:
        batch_op.alter_column(
            "consumer_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("direct_orders") as batch_op:
        batch_op.alter_column(
            "consumer_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
