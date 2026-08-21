"""REST endpoints for stores, POI mirrors, candidates, and mappings."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.ports import Capability
from poi_admin.connections.service import ConnectionService
from poi_admin.core.config import Settings
from poi_admin.core.database import get_session
from poi_admin.core.dependencies import (
    AuthContext,
    auth_error,
    require_csrf,
    require_permission,
)
from poi_admin.core.permissions import Permission
from poi_admin.operations.service import OperationService

from .operations import POI_SYNC_COMMAND
from .schemas import (
    CandidateResponse,
    ManualMappingRequest,
    MappingResponse,
    PoiResponse,
    PoiSyncAcceptedResponse,
    PoiSyncRequest,
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
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_STORES))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoreResponse:
    del csrf_context
    try:
        store = await StoreService(session).create_store(
            _tenant_id(context), **payload.model_dump()
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
) -> Response:
    del csrf_context
    try:
        await StoreService(session).archive_store(_tenant_id(context), store_id)
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
