"""FastAPI application factory and process resource lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .audit.router import audit_router
from .connections.router import connection_router
from .core.config import Settings, get_settings
from .core.database import create_database
from .core.health import health_router
from .core.license_router import license_router
from .core.licensing import license_enforcement_middleware, load_license
from .core.observability import request_context_middleware
from .dashboard.router import dashboard_router
from .identity.router import identity_router
from .local_life.router_accounting import accounting_router
from .local_life.router_orders import order_router
from .local_life.router_products import product_router
from .operations.router import operation_router
from .operations.service import IdempotencyConflictError
from .stores.router import store_router
from .webhooks.router import webhook_events_router, webhook_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    database = create_database(application.state.settings)
    settings = application.state.settings
    http_client = httpx.AsyncClient(
        timeout=15.0,
        limits=httpx.Limits(
            max_connections=settings.wechat_http_max_connections,
            max_keepalive_connections=settings.wechat_http_max_keepalive_connections,
        ),
    )
    application.state.database = database
    application.state.db = database
    application.state.http_client = http_client
    application.state.license = load_license(settings)
    try:
        yield
    finally:
        await http_client.aclose()
        await database.dispose()
        application.state.http_client = None
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
    application.middleware("http")(license_enforcement_middleware)
    application.middleware("http")(request_context_middleware)

    @application.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(
        request: Request, error: IdempotencyConflictError
    ) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        return JSONResponse(
            status_code=409,
            content={
                "code": "idempotency_key_conflict",
                "message": str(error),
                "correlation_id": correlation_id,
            },
        )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(license_router, prefix="/api/v1")
    application.include_router(dashboard_router, prefix="/api/v1")
    application.include_router(identity_router, prefix="/api/v1")
    application.include_router(connection_router, prefix="/api/v1")
    application.include_router(operation_router, prefix="/api/v1")
    application.include_router(store_router, prefix="/api/v1")
    application.include_router(product_router, prefix="/api/v1")
    application.include_router(order_router, prefix="/api/v1")
    application.include_router(accounting_router, prefix="/api/v1")
    application.include_router(webhook_router, prefix="/api/v1")
    application.include_router(webhook_events_router, prefix="/api/v1")
    application.include_router(audit_router, prefix="/api/v1")
    return application


app = create_app()


__all__ = ["app", "create_app", "lifespan"]
