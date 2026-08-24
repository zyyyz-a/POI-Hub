"""Tenant connection management endpoints; credential fields never leave the server."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.config import Settings
from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, require_csrf, require_permission
from poi_admin.core.permissions import Permission

from .models import WeChatConnection
from .schemas import ConnectionCreateRequest, ConnectionResponse
from .service import ConnectionService, ConnectionServiceError

connection_router = APIRouter(prefix="/connections", tags=["connections"])


def _service(request: Request, session: AsyncSession) -> ConnectionService:
    return ConnectionService(session, cast(Settings, request.app.state.settings))


def _raise(error: ConnectionServiceError) -> None:
    from poi_admin.core.dependencies import auth_error

    raise auth_error(error.code, error.message, error.status_code)


def _response(connection: WeChatConnection) -> ConnectionResponse:
    return ConnectionResponse.model_validate(ConnectionService.public(connection))


@connection_router.get("", response_model=list[ConnectionResponse])
async def list_connections(
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_CONNECTIONS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ConnectionResponse]:
    if context.tenant is None:
        from poi_admin.core.dependencies import auth_error

        raise auth_error("tenant_required", "请先选择租户", 400)
    return [_response(item) for item in await _service(request, session).list(context.tenant.id)]


@connection_router.post("", status_code=status.HTTP_201_CREATED, response_model=ConnectionResponse)
async def create_connection(
    payload: ConnectionCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_CONNECTIONS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConnectionResponse:
    del csrf_context
    if context.tenant is None:
        from poi_admin.core.dependencies import auth_error

        raise auth_error("tenant_required", "请先选择租户", 400)
    try:
        connection = await _service(request, session).create(
            context.tenant.id,
            capability=payload.capability,
            mode=payload.mode,
            app_id=payload.app_id,
            merchant_id=payload.merchant_id,
            secrets=payload.secrets,
            mock_scenario=payload.mock_scenario,
        )
    except ConnectionServiceError as error:
        _raise(error)
    return _response(connection)


@connection_router.put("/{connection_id}/secrets", response_model=ConnectionResponse)
async def update_connection_secrets(
    connection_id: str,
    payload: dict[str, str],
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_CONNECTIONS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConnectionResponse:
    del csrf_context
    if context.tenant is None:
        from poi_admin.core.dependencies import auth_error

        raise auth_error("tenant_required", "请先选择租户", 400)
    try:
        connection = await _service(request, session).update_secrets(
            context.tenant.id, connection_id, payload
        )
    except ConnectionServiceError as error:
        _raise(error)
    return _response(connection)


__all__ = ["connection_router"]
