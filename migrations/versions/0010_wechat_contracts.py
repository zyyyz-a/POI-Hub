"""Encrypted operation/callback payloads and durable voucher metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_wechat_contracts"
down_revision: str | None = "0009_batch_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("integration_operations") as batch_op:
        batch_op.add_column(sa.Column("encrypted_payload", sa.Text(), nullable=True))
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.add_column(sa.Column("encrypted_payload", sa.Text(), nullable=True))
    with op.batch_alter_table("local_vouchers") as batch_op:
        batch_op.add_column(sa.Column("code_ciphertext", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("last_consume_request_no", sa.String(length=128), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("local_vouchers") as batch_op:
        batch_op.drop_column("last_consume_request_no")
        batch_op.drop_column("code_ciphertext")
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.drop_column("encrypted_payload")
    with op.batch_alter_table("integration_operations") as batch_op:
        batch_op.drop_column("encrypted_payload")
