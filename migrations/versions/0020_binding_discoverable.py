"""Add discoverable flag to store entry bindings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_binding_discoverable"
down_revision: str | None = "0019_store_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mini_program_store_bindings",
        sa.Column(
            "discoverable", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )


def downgrade() -> None:
    op.drop_column("mini_program_store_bindings", "discoverable")
