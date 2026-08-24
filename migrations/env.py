"""Alembic environment configured for SQLAlchemy's async engine."""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from poi_admin.audit import models as audit_models  # noqa: E402, F401
from poi_admin.connections import models as connection_models  # noqa: E402, F401
from poi_admin.core.config import get_settings  # noqa: E402
from poi_admin.core.database import ensure_database_directory  # noqa: E402
from poi_admin.core.orm import Base  # noqa: E402
from poi_admin.identity import models as identity_models  # noqa: E402, F401
from poi_admin.local_life import models as local_life_models  # noqa: E402, F401
from poi_admin.operations import models as operation_models  # noqa: E402, F401
from poi_admin.stores import models as store_models  # noqa: E402, F401
from poi_admin.webhooks import models as webhook_models  # noqa: E402, F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    configured_url = os.getenv("DATABASE_URL")
    if configured_url:
        return configured_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url and not ini_url.startswith("sqlite+aiosqlite:///./.data"):
        return ini_url
    return get_settings().database_url


def run_migrations_offline() -> None:
    url = database_url()
    ensure_database_directory(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = database_url()
    ensure_database_directory(url)
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
