"""REST endpoints for stores, POI mirrors, candidates, and mappings."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.crypto import redact_secrets
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, GatewayError, ServicePoiGateway
from poi_admin.connections.service import ConnectionService
from poi_admin.core.config import Settings
from poi_admin.core.database import get_session
from poi_admin.core.dependencies import (
    AuthContext,
    auth_error,
    require_csrf,
    require_permission,
)
from poi_admin.core.licensing import LicenseState
from poi_admin.core.permissions import Permission
from poi_admin.operations.service import OperationService

from .models import Store
from .operations import (
    POI_AUDIT_COMMAND,
    POI_CREATE_COMMAND,
    POI_DELETE_COMMAND,
    POI_SYNC_COMMAND,
    POI_UPDATE_COMMAND,
)
from .schemas import (
    CandidateResponse,
    ManualMappingRequest,
    MappingResponse,
    PoiActionRequest,
    PoiCreateRequest,
    PoiOperationAcceptedResponse,
    PoiResponse,
    PoiSyncAcceptedResponse,
    PoiSyncRequest,
    PoiUpdateRequest,
    RemotePoiResponse,
    StoreCreateRequest,
    StoreResponse,
    StoreUpdateRequest,
)
from .service import StoreService, StoreServiceError

store_router = APIRouter(tags=["stores"])


def _tenant_id(context: AuthContext) -> str:
    if context.tenant is None:
        raise auth_error("tenant_required", "请先选择租户", 400)
    return context.tenant.id


def _raise(error: StoreServiceError) -> None:
    raise auth_error(error.code, error.message, error.status_code)


@store_router.get("/stores", response_model=list[StoreResponse])
async def list_stores(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_STORES))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StoreResponse]:
    stores = await StoreService(session).list_stores(_tenant_id(context))
    return [StoreResponse.model_validate(item) for item in stores]


@store_router.post(
    "/stores", response_model=StoreResponse, status_code=status.HTTP_201_CREATED
)
async def create_store(
    payload: StoreCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_STORES))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoreResponse:
    del csrf_context
    tenant_id = _tenant_id(context)
    license_state: LicenseState = request.app.state.license
    if (
        license_state.mode == "enforce"
        and license_state.current_status() == "valid"
        and license_state.claims is not None
    ):
        store_count = await session.scalar(
            select(func.count())
            .select_from(Store)
            .where(Store.tenant_id == tenant_id, Store.status != "archived")
        )
        if int(store_count or 0) >= license_state.claims.max_stores:
            raise auth_error(
                "license_store_limit",
                "已达到当前软件服务授权的门店数量上限",
                402,
            )
    try:
        store = await StoreService(session).create_store(
            tenant_id, **payload.model_dump()
        )
    except StoreServiceError as error:
        _raise(error)
    return StoreResponse.model_validate(store)


@store_router.get("/stores/{store_id}", response_model=StoreResponse)
async def get_store(
    store_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_STORES))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoreResponse:
    store = await StoreService(session).get_store(_tenant_id(context), store_id)
    if store is None:
        raise auth_error("store_not_found", "门店不存在", 404)
    return StoreResponse.model_validate(store)


@store_router.patch("/stores/{store_id}", response_model=StoreResponse)
async def update_store(
    store_id: str,
    payload: StoreUpdateRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_STORES))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoreResponse:
    del csrf_context
    changes = payload.model_dump(exclude={"version"}, exclude_unset=True)
    try:
        store = await StoreService(session).update_store(
            _tenant_id(context), store_id, payload.version, changes
        )
    except StoreServiceError as error:
        _raise(error)
    return StoreResponse.model_validate(store)


@store_router.delete("/stores/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_store(
    store_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_STORES))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
    version: int = Query(ge=1),
) -> Response:
    del csrf_context
    try:
        await StoreService(session).archive_store(
            _tenant_id(context), store_id, version, context.user.id
        )
    except StoreServiceError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@store_router.get("/pois", response_model=list[PoiResponse])
async def list_pois(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_STORES))],
    session: Annotated[AsyncSession, Depends(get_session)],
    connection_id: str | None = None,
) -> list[PoiResponse]:
    pois = await StoreService(session).list_pois(_tenant_id(context), connection_id)
    return [PoiResponse.model_validate(item) for item in pois]


async def _poi_connection(
    request: Request, session: AsyncSession, tenant_id: str, connection_id: str
) -> tuple[ConnectionService, WeChatConnection]:
    connection_service = ConnectionService(
        session,
        cast(Settings, request.app.state.settings),
        http_client=request.app.state.http_client,
    )
    connection = await connection_service.get(tenant_id, connection_id)
    if connection is None:
        raise auth_error("connection_not_found", "连接不存在", 404)
    if connection.capability != Capability.SERVICE_POI.value:
        raise auth_error("invalid_connection", "连接不支持服务 POI", 422)
    return connection_service, connection


@store_router.get("/pois/search", response_model=list[RemotePoiResponse])
async def search_pois(
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_STORES))],
    session: Annotated[AsyncSession, Depends(get_session)],
    keyword: str = Query(min_length=1, max_length=160),
    connection_id: str = Query(min_length=1),
) -> list[RemotePoiResponse]:
    connection_service, _ = await _poi_connection(
        request, session, _tenant_id(context), connection_id
    )
    try:
        gateway = cast(
            ServicePoiGateway,
            await connection_service.gateway(_tenant_id(context), connection_id),
        )
        results = await gateway.search_pois(keyword)
    except GatewayError as error:
        raise auth_error(error.code, str(error), 503 if error.retryable else 422) from error
    return [
        RemotePoiResponse(
            poi_id=item.poi_id,
            name=item.name,
            address=item.address,
            latitude=item.latitude,
            longitude=item.longitude,
            status=item.status,
        )
        for item in results
    ]


async def _enqueue_poi(
    session: AsyncSession,
    tenant_id: str,
    connection_id: str,
    command: str,
    idempotency_key: str,
    payload: dict[str, Any],
    settings: Settings,
) -> PoiOperationAcceptedResponse:
    service = OperationService(session, settings.encryption_key)
    existing = await service.get_by_idempotency_key(tenant_id, idempotency_key)
    if existing is not None:
        if (
            existing.command_type != command
            or existing.connection_id != connection_id
            or existing.payload != redact_secrets(payload)
        ):
            raise auth_error("idempotency_key_conflict", "幂等键已用于其他操作", 409)
        return PoiOperationAcceptedResponse(operation_id=existing.id, status=existing.status)
    operation = await service.enqueue(
        tenant_id,
        command,
        idempotency_key,
        payload,
        connection_id=connection_id,
        resource_ref=(f"service_poi:{payload['poi_id']}" if payload.get("poi_id") else None),
    )
    return PoiOperationAcceptedResponse(operation_id=operation.id, status=operation.status)


@store_router.post(
    "/pois", response_model=PoiOperationAcceptedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_poi(
    payload: PoiCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MAPPINGS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PoiOperationAcceptedResponse:
    del csrf_context
    tenant_id = _tenant_id(context)
    await _poi_connection(request, session, tenant_id, payload.connection_id)
    body = payload.model_dump(exclude={"connection_id", "idempotency_key"}, exclude_none=True)
    return await _enqueue_poi(
        session,
        tenant_id,
        payload.connection_id,
        POI_CREATE_COMMAND,
        payload.idempotency_key,
        body,
        cast(Settings, request.app.state.settings),
    )


@store_router.patch(
    "/pois/{poi_id}",
    response_model=PoiOperationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_poi(
    poi_id: str,
    payload: PoiUpdateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MAPPINGS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PoiOperationAcceptedResponse:
    del csrf_context
    tenant_id = _tenant_id(context)
    poi = await StoreService(session).get_poi(tenant_id, poi_id)
    if poi is None:
        raise auth_error("poi_not_found", "POI 不存在", 404)
    body = {"poi_id": poi_id, **payload.model_dump(exclude={"idempotency_key"}, exclude_none=True)}
    await _poi_connection(request, session, tenant_id, poi.connection_id)
    return await _enqueue_poi(
        session,
        tenant_id,
        poi.connection_id,
        POI_UPDATE_COMMAND,
        payload.idempotency_key,
        body,
        cast(Settings, request.app.state.settings),
    )


@store_router.post(
    "/pois/{poi_id}/delete",
    response_model=PoiOperationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_poi(
    poi_id: str,
    payload: PoiActionRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MAPPINGS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PoiOperationAcceptedResponse:
    del csrf_context
    tenant_id = _tenant_id(context)
    poi = await StoreService(session).get_poi(tenant_id, poi_id)
    if poi is None:
        raise auth_error("poi_not_found", "POI 不存在", 404)
    await _poi_connection(request, session, tenant_id, poi.connection_id)
    return await _enqueue_poi(
        session,
        tenant_id,
        poi.connection_id,
        POI_DELETE_COMMAND,
        payload.idempotency_key,
        {"poi_id": poi_id},
        cast(Settings, request.app.state.settings),
    )


@store_router.post(
    "/pois/{poi_id}/audit-refresh",
    response_model=PoiOperationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_poi_audit(
    poi_id: str,
    payload: PoiActionRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MAPPINGS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PoiOperationAcceptedResponse:
    del csrf_context
    tenant_id = _tenant_id(context)
    poi = await StoreService(session).get_poi(tenant_id, poi_id)
    if poi is None:
        raise auth_error("poi_not_found", "POI 不存在", 404)
    await _poi_connection(request, session, tenant_id, poi.connection_id)
    return await _enqueue_poi(
        session,
        tenant_id,
        poi.connection_id,
        POI_AUDIT_COMMAND,
        payload.idempotency_key,
        {"poi_id": poi_id},
        cast(Settings, request.app.state.settings),
    )


@store_router.post(
    "/pois/sync",
    response_model=PoiSyncAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_pois(
    payload: PoiSyncRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MAPPINGS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PoiSyncAcceptedResponse:
    del csrf_context
    tenant_id = _tenant_id(context)
    connection_service = ConnectionService(
        session, cast(Settings, request.app.state.settings)
    )
    connection = await connection_service.get(tenant_id, payload.connection_id)
    if connection is None:
        raise auth_error("connection_not_found", "连接不存在", 404)
    if connection.capability != Capability.SERVICE_POI.value:
        raise auth_error("invalid_connection", "连接不支持服务商 POI", 422)
    operation = await OperationService(session).enqueue(
        tenant_id,
        POI_SYNC_COMMAND,
        payload.idempotency_key,
        {"actor_user_id": context.user.id},
        connection_id=connection.id,
    )
    return PoiSyncAcceptedResponse(operation_id=operation.id, status=operation.status)


@store_router.get("/match-candidates", response_model=list[CandidateResponse])
async def list_candidates(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_MAPPINGS))],
    session: Annotated[AsyncSession, Depends(get_session)],
    include_dismissed: bool = False,
) -> list[CandidateResponse]:
    candidates = await StoreService(session).list_candidates(
        _tenant_id(context), include_dismissed=include_dismissed
    )
    return [CandidateResponse.model_validate(item) for item in candidates]


@store_router.post(
    "/match-candidates/{candidate_id}/confirm",
    response_model=MappingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_candidate(
    candidate_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MAPPINGS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MappingResponse:
    del csrf_context
    try:
        mapping = await StoreService(session).confirm_candidate(
            _tenant_id(context), candidate_id, context.user.id
        )
    except StoreServiceError as error:
        _raise(error)
    return MappingResponse.model_validate(mapping)


@store_router.post(
    "/match-candidates/{candidate_id}/dismiss", response_model=CandidateResponse
)
async def dismiss_candidate(
    candidate_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MAPPINGS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CandidateResponse:
    del csrf_context
    try:
        candidate = await StoreService(session).dismiss_candidate(
            _tenant_id(context), candidate_id, context.user.id
        )
    except StoreServiceError as error:
        _raise(error)
    return CandidateResponse.model_validate(candidate)


@store_router.get("/store-poi-mappings", response_model=list[MappingResponse])
async def list_mappings(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_MAPPINGS))],
    session: Annotated[AsyncSession, Depends(get_session)],
    include_history: bool = False,
) -> list[MappingResponse]:
    mappings = await StoreService(session).list_mappings(
        _tenant_id(context), include_history=include_history
    )
    return [MappingResponse.model_validate(item) for item in mappings]


@store_router.post(
    "/store-poi-mappings/manual",
    response_model=MappingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def manual_map(
    payload: ManualMappingRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MAPPINGS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MappingResponse:
    del csrf_context
    try:
        mapping = await StoreService(session).manual_map(
            _tenant_id(context), payload.store_id, payload.service_poi_id, context.user.id
        )
    except StoreServiceError as error:
        _raise(error)
    return MappingResponse.model_validate(mapping)


@store_router.post(
    "/store-poi-mappings/{mapping_id}/unbind", response_model=MappingResponse
)
async def unbind_mapping(
    mapping_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MAPPINGS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MappingResponse:
    del csrf_context
    try:
        mapping = await StoreService(session).unbind_mapping(
            _tenant_id(context), mapping_id, context.user.id
        )
    except StoreServiceError as error:
        _raise(error)
    return MappingResponse.model_validate(mapping)


__all__ = ["store_router"]
