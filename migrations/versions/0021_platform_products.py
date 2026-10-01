"""Decouple platform products and orders from merchant mini-programs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_platform_products"
down_revision: str | None = "0020_binding_discoverable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("direct_products") as batch_op:
        batch_op.alter_column(
            "mini_program_id", existing_type=sa.String(length=36), nullable=True
        )
        batch_op.add_column(
            sa.Column("platform_mini_program_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_direct_product_platform_program",
            "platform_mini_programs",
            ["platform_mini_program_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_direct_products_platform_mini_program_id", ["platform_mini_program_id"]
        )
    with op.batch_alter_table("direct_orders") as batch_op:
        batch_op.alter_column(
            "mini_program_id", existing_type=sa.String(length=36), nullable=True
        )


def downgrade() -> None:
    with op.batch_alter_table("direct_orders") as batch_op:
        batch_op.alter_column(
            "mini_program_id", existing_type=sa.String(length=36), nullable=False
        )
    with op.batch_alter_table("direct_products") as batch_op:
        batch_op.drop_index("ix_direct_products_platform_mini_program_id")
        batch_op.drop_constraint("fk_direct_product_platform_program", type_="foreignkey")
        batch_op.drop_column("platform_mini_program_id")
        batch_op.alter_column(
            "mini_program_id", existing_type=sa.String(length=36), nullable=False
        )
