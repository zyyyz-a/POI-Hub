"""FastAPI application factory and process resource lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .connections.router import connection_router
from .core.config import Settings, get_settings
from .core.database import create_database
from .core.health import health_router
from .identity.router import identity_router
from .operations.router import operation_router
from .stores.router import store_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    database = create_database(application.state.settings)
    application.state.database = database
    application.state.db = database
    try:
        yield
    finally:
        await database.dispose()
        application.state.database = None
        application.state.db = None


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(identity_router, prefix="/api/v1")
    application.include_router(connection_router, prefix="/api/v1")
    application.include_router(operation_router, prefix="/api/v1")
    application.include_router(store_router, prefix="/api/v1")
    return application


app = create_app()


__all__ = ["app", "create_app", "lifespan"]
