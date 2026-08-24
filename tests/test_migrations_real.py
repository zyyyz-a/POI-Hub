from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

# ruff: noqa: E501


def _upgrade(database_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_fresh_database_can_run_real_alembic_upgrade_and_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.sqlite3"

    first = _upgrade(database_path)
    assert first.returncode == 0, first.stdout + first.stderr
    second = _upgrade(database_path)
    assert second.returncode == 0, second.stdout + second.stderr

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        expected = {
            "users",
            "tenants",
            "memberships",
            "sessions",
            "invitations",
            "wechat_connections",
            "integration_operations",
            "stores",
            "service_pois",
            "store_poi_mappings",
            "local_products",
            "local_skus",
            "local_orders",
            "local_vouchers",
            "local_after_sales",
            "local_funds_flows",
            "local_voucher_bills",
            "webhook_events",
            "audit_logs",
        }
        assert expected <= tables
        with engine.connect() as connection:
            revision = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
            assert revision == "0010_wechat_contracts"
        assert any(
            index["name"] == "ix_operation_claimable"
            for index in inspector.get_indexes("integration_operations")
        )
        assert any(
            index["name"] == "ix_webhook_claimable"
            for index in inspector.get_indexes("webhook_events")
        )
        constraints = inspector.get_unique_constraints("local_orders")
        assert any(item["name"] == "uq_local_order_external_id" for item in constraints)
    finally:
        engine.dispose()
