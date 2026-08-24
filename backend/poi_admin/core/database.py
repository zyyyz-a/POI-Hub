"""Async SQLAlchemy engine and session ownership."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import Settings


def ensure_database_directory(database_url: str) -> None:
    """Create a file-backed SQLite parent directory when it is needed."""

    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return
    database = url.database
    if not database or database == ":memory:":
        return
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class Database:
    """Resources owned by one application instance."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def check_database(self) -> None:
        """Raise if the configured database cannot execute a trivial query."""

        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a scoped session for request/dependency use."""

        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        """Dispose all pooled connections owned by this app instance."""

        await self.engine.dispose()


def create_engine(settings: Settings) -> AsyncEngine:
    """Build an async engine for settings."""

    ensure_database_directory(settings.database_url)
    url = make_url(settings.database_url)
    connect_args: dict[str, object] = {}
    if url.drivername.startswith("sqlite"):
        connect_args["timeout"] = settings.sqlite_busy_timeout_ms / 1000
    engine = create_async_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    if url.drivername.startswith("sqlite"):
        _configure_sqlite(engine, settings.sqlite_busy_timeout_ms)
    return engine


def _configure_sqlite(engine: AsyncEngine, busy_timeout_ms: int) -> None:
    """Enable integrity and bounded write-wait behavior on every SQLite connection."""

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the async session factory owned by one engine."""

    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def create_database(settings: Settings) -> Database:
    """Build an engine and session factory for settings."""

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    return Database(engine=engine, session_factory=session_factory)


async def check_database(database: Database) -> None:
    """Functional helper for health checks and startup probes."""

    await database.check_database()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session owned by the current app."""

    database = getattr(request.app.state, "database", None)
    if not isinstance(database, Database):
        raise RuntimeError("database is not initialized")
    async with database.session_factory() as session:
        yield session


__all__ = [
    "Database",
    "check_database",
    "create_database",
    "create_engine",
    "create_session_factory",
    "ensure_database_directory",
    "get_session",
]
