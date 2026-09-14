"""Qualification, official filing, merchant mini-programs, and position services."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_position_onboarding"
down_revision: str | None = "0010_wechat_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "merchant_onboarding_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("route", sa.String(length=50), nullable=False),
        sa.Column("category_code", sa.String(length=100), nullable=False),
        sa.Column("category_name", sa.String(length=160), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("region_code", sa.String(length=32), nullable=True),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("precheck_status", sa.String(length=40), nullable=False),
        sa.Column("precheck_report", sa.JSON(), nullable=False),
        sa.Column("official_status", sa.String(length=40), nullable=False),
        sa.Column("official_reference", sa.String(length=200), nullable=True),
        sa.Column("official_evidence_reference", sa.String(length=500), nullable=True),
        sa.Column("official_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("official_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position_status", sa.String(length=40), nullable=False),
        sa.Column("blocker_code", sa.String(length=100), nullable=True),
        sa.Column("blocker_message", sa.String(length=500), nullable=True),
        sa.Column("next_action", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "store_id", "route", "category_code", name="uq_onboarding_route"
        ),
    )
    op.create_index(
        "ix_onboarding_tenant_stage", "merchant_onboarding_cases", ["tenant_id", "stage"]
    )
    op.create_index(
        "ix_onboarding_tenant_official",
        "merchant_onboarding_cases",
        ["tenant_id", "official_status"],
    )
    op.create_index(
        "ix_merchant_onboarding_cases_tenant_id",
        "merchant_onboarding_cases",
        ["tenant_id"],
    )
    op.create_index(
        "ix_merchant_onboarding_cases_store_id",
        "merchant_onboarding_cases",
        ["store_id"],
    )

    op.create_table(
        "merchant_mini_programs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=True),
        sa.Column("owner_subject", sa.String(length=200), nullable=False),
        sa.Column("ownership_mode", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("authorization_reference", sa.String(length=500), nullable=True),
        sa.Column("payment_merchant_id", sa.String(length=128), nullable=True),
        sa.Column("payment_owner_verified", sa.Boolean(), nullable=False),
        sa.Column("video_channel_id", sa.String(length=160), nullable=True),
        sa.Column("location_service_status", sa.String(length=40), nullable=False),
        sa.Column("callback_configured", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["connection_id"], ["wechat_connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "app_id", name="uq_mini_program_tenant_appid"),
    )
    op.create_index(
        "ix_mini_program_tenant_status", "merchant_mini_programs", ["tenant_id", "status"]
    )
    op.create_index("ix_merchant_mini_programs_tenant_id", "merchant_mini_programs", ["tenant_id"])
    op.create_index(
        "ix_merchant_mini_programs_connection_id", "merchant_mini_programs", ["connection_id"]
    )

    op.create_table(
        "position_service_mounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("onboarding_case_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("service_poi_id", sa.String(length=36), nullable=True),
        sa.Column("mini_program_id", sa.String(length=36), nullable=False),
        sa.Column("service_type", sa.String(length=50), nullable=False),
        sa.Column("service_name", sa.String(length=80), nullable=False),
        sa.Column("entry_path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("official_reference", sa.String(length=200), nullable=True),
        sa.Column("evidence_reference", sa.String(length=500), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mounted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["onboarding_case_id"], ["merchant_onboarding_cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["mini_program_id"], ["merchant_mini_programs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["service_poi_id"], ["service_pois.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "store_id",
            "mini_program_id",
            "service_type",
            name="uq_position_service_mount",
        ),
    )
    op.create_index(
        "ix_position_mount_tenant_status", "position_service_mounts", ["tenant_id", "status"]
    )
    for column in (
        "tenant_id",
        "onboarding_case_id",
        "store_id",
        "service_poi_id",
        "mini_program_id",
    ):
        op.create_index(f"ix_position_service_mounts_{column}", "position_service_mounts", [column])


def downgrade() -> None:
    op.drop_table("position_service_mounts")
    op.drop_table("merchant_mini_programs")
    op.drop_table("merchant_onboarding_cases")
