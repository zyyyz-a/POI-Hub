"""Canonical stores, mirrored service POIs, candidates, and mapping history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_stores_pois"
down_revision: str | None = "0003_connections_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("contact_phone_masked", sa.String(length=32), nullable=True),
        sa.Column("province", sa.String(length=80), nullable=True),
        sa.Column("city", sa.String(length=80), nullable=True),
        sa.Column("district", sa.String(length=80), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_store_tenant_code"),
    )
    op.create_index("ix_stores_tenant_id", "stores", ["tenant_id"])
    op.create_index("ix_store_tenant_status", "stores", ["tenant_id", "status"])

    op.create_table(
        "service_pois",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("external_poi_id", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("remote_status", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=160), nullable=True),
        sa.Column("qualification_summary", sa.JSON(), nullable=True),
        sa.Column("raw_checksum", sa.String(length=64), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["wechat_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "connection_id", "external_poi_id", name="uq_poi_remote_id"
        ),
    )
    op.create_index("ix_service_pois_tenant_id", "service_pois", ["tenant_id"])
    op.create_index("ix_service_pois_connection_id", "service_pois", ["connection_id"])
    op.create_index("ix_poi_tenant_connection", "service_pois", ["tenant_id", "connection_id"])

    op.create_table(
        "match_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("service_poi_id", sa.String(length=36), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("name_score", sa.Float(), nullable=False),
        sa.Column("address_score", sa.Float(), nullable=False),
        sa.Column("distance_score", sa.Float(), nullable=False),
        sa.Column("distance_meters", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by_user_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["wechat_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dismissed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["service_poi_id"], ["service_pois.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "store_id", "service_poi_id", name="uq_candidate_store_poi"
        ),
    )
    op.create_index("ix_match_candidates_tenant_id", "match_candidates", ["tenant_id"])
    op.create_index("ix_match_candidates_connection_id", "match_candidates", ["connection_id"])
    op.create_index("ix_match_candidates_store_id", "match_candidates", ["store_id"])
    op.create_index("ix_match_candidates_service_poi_id", "match_candidates", ["service_poi_id"])
    op.create_index("ix_candidate_tenant_score", "match_candidates", ["tenant_id", "total_score"])

    op.create_table(
        "store_poi_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.String(length=36), nullable=False),
        sa.Column("service_poi_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("match_evidence", sa.JSON(), nullable=False),
        sa.Column("confirmed_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unbound_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["connection_id"], ["wechat_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_poi_id"], ["service_pois.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unbound_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_store_poi_mappings_tenant_id", "store_poi_mappings", ["tenant_id"])
    op.create_index("ix_store_poi_mappings_connection_id", "store_poi_mappings", ["connection_id"])
    op.create_index("ix_store_poi_mappings_store_id", "store_poi_mappings", ["store_id"])
    op.create_index(
        "ix_store_poi_mappings_service_poi_id", "store_poi_mappings", ["service_poi_id"]
    )
    op.create_index("ix_mapping_tenant_state", "store_poi_mappings", ["tenant_id", "state"])
    predicate = sa.text("state = 'active'")
    op.create_index(
        "uq_active_mapping_store",
        "store_poi_mappings",
        ["tenant_id", "connection_id", "store_id"],
        unique=True,
        sqlite_where=predicate,
        postgresql_where=predicate,
    )
    op.create_index(
        "uq_active_mapping_poi",
        "store_poi_mappings",
        ["tenant_id", "connection_id", "service_poi_id"],
        unique=True,
        sqlite_where=predicate,
        postgresql_where=predicate,
    )


def downgrade() -> None:
    op.drop_index("uq_active_mapping_poi", table_name="store_poi_mappings")
    op.drop_index("uq_active_mapping_store", table_name="store_poi_mappings")
    op.drop_index("ix_mapping_tenant_state", table_name="store_poi_mappings")
    op.drop_index("ix_store_poi_mappings_service_poi_id", table_name="store_poi_mappings")
    op.drop_index("ix_store_poi_mappings_store_id", table_name="store_poi_mappings")
    op.drop_index("ix_store_poi_mappings_connection_id", table_name="store_poi_mappings")
    op.drop_index("ix_store_poi_mappings_tenant_id", table_name="store_poi_mappings")
    op.drop_table("store_poi_mappings")
    op.drop_index("ix_candidate_tenant_score", table_name="match_candidates")
    op.drop_index("ix_match_candidates_service_poi_id", table_name="match_candidates")
    op.drop_index("ix_match_candidates_store_id", table_name="match_candidates")
    op.drop_index("ix_match_candidates_connection_id", table_name="match_candidates")
    op.drop_index("ix_match_candidates_tenant_id", table_name="match_candidates")
    op.drop_table("match_candidates")
    op.drop_index("ix_poi_tenant_connection", table_name="service_pois")
    op.drop_index("ix_service_pois_connection_id", table_name="service_pois")
    op.drop_index("ix_service_pois_tenant_id", table_name="service_pois")
    op.drop_table("service_pois")
    op.drop_index("ix_store_tenant_status", table_name="stores")
    op.drop_index("ix_stores_tenant_id", table_name="stores")
    op.drop_table("stores")
