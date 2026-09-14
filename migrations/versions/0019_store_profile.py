"""Store presentation fields for the customer storefront."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_store_profile"
down_revision: str | None = "0018_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("cover_image", sa.String(length=500), nullable=True))
    op.add_column("stores", sa.Column("logo", sa.String(length=500), nullable=True))
    op.add_column(
        "stores", sa.Column("business_hours", sa.String(length=120), nullable=True)
    )
    op.add_column("stores", sa.Column("public_phone", sa.String(length=32), nullable=True))
    op.add_column("stores", sa.Column("intro", sa.Text(), nullable=True))
    op.add_column(
        "stores",
        sa.Column(
            "environment_images",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column("stores", sa.Column("service_guarantees", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("appointment_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in (
        "appointment_notes",
        "service_guarantees",
        "environment_images",
        "intro",
        "public_phone",
        "business_hours",
        "logo",
        "cover_image",
    ):
        op.drop_column("stores", column)
