"""Enforce single-quantity direct orders so one order always maps to one voucher."""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_single_quantity_orders"
down_revision: str | None = "0014_platform_order_consumer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("direct_orders") as batch_op:
        batch_op.drop_constraint("ck_direct_order_quantity", type_="check")
        batch_op.create_check_constraint("ck_direct_order_quantity", "quantity = 1")


def downgrade() -> None:
    with op.batch_alter_table("direct_orders") as batch_op:
        batch_op.drop_constraint("ck_direct_order_quantity", type_="check")
        batch_op.create_check_constraint("ck_direct_order_quantity", "quantity > 0")
