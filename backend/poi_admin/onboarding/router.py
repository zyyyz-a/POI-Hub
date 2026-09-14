"""Authenticated onboarding and position-service endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.audit.service import AuditService
from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, auth_error, require_csrf, require_permission
from poi_admin.core.permissions import Permission, has_permission

from .schemas import (
    MiniProgramCreate,
    MiniProgramResponse,
    MiniProgramUpdate,
    OfficialDecisionRequest,
    OfficialSubmissionRequest,
    OnboardingCaseCreate,
    OnboardingCaseResponse,
    OnboardingReadinessResponse,
    PlatformMiniProgramCreate,
    PlatformMiniProgramResponse,
    PlatformMiniProgramUpdate,
    PositionServiceCreate,
    PositionServiceResponse,
    PositionServiceTransition,
    PrecheckRequest,
    StoreBindingCreate,
    StoreBindingResponse,
    StoreBindingUpdate,
)
from .service import OnboardingError, OnboardingService

onboarding_router = APIRouter(tags=["onboarding"])


def _tenant_id(context: AuthContext) -> str:
    if context.tenant is None:
        raise auth_error("tenant_required", "请先选择租户", 400)
    return context.tenant.id


def _raise(error: OnboardingError) -> None:
    raise auth_error(error.code, error.message, error.status_code)


async def _audit(
    session: AsyncSession,
    request: Request,
    context: AuthContext,
    action: str,
    resource_type: str,
    resource_id: str,
    after: dict[str, Any],
) -> None:
    await AuditService(session).record(
        tenant_id=_tenant_id(context),
        actor_user_id=context.user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        after=after,
        correlation_id=getattr(request.state, "correlation_id", None),
    )


@onboarding_router.get("/onboarding/cases", response_model=list[OnboardingCaseResponse])
async def list_cases(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ONBOARDING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[OnboardingCaseResponse]:
    rows = await OnboardingService(session).list_cases(_tenant_id(context))
    return [OnboardingCaseResponse.model_validate(item) for item in rows]


@onboarding_router.post(
    "/onboarding/cases",
    response_model=OnboardingCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_case(
    payload: OnboardingCaseCreate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingCaseResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).create_case(
            _tenant_id(context),
            context.user.id,
            payload.model_dump(mode="json"),
        )
    except OnboardingError as error:
        _raise(error)
    response = OnboardingCaseResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "onboarding.case.created",
        "onboarding_case",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@onboarding_router.post(
    "/onboarding/cases/{case_id}/precheck", response_model=OnboardingCaseResponse
)
async def run_precheck(
    case_id: str,
    payload: PrecheckRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingCaseResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).run_precheck(
            _tenant_id(context),
            case_id,
            context.user.id,
            [item.model_dump(mode="json") for item in payload.items],
            payload.rule_source_reference,
        )
    except OnboardingError as error:
        _raise(error)
    response = OnboardingCaseResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "onboarding.precheck.evaluated",
        "onboarding_case",
        row.id,
        {"precheck_status": row.precheck_status, "report": row.precheck_report},
    )
    return response


@onboarding_router.post(
    "/onboarding/cases/{case_id}/official-submission", response_model=OnboardingCaseResponse
)
async def record_official_submission(
    case_id: str,
    payload: OfficialSubmissionRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingCaseResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).record_official_submission(
            _tenant_id(context),
            case_id,
            context.user.id,
            payload.official_reference,
            payload.evidence_reference,
        )
    except OnboardingError as error:
        _raise(error)
    response = OnboardingCaseResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "onboarding.official.submitted",
        "onboarding_case",
        row.id,
        {"official_reference": row.official_reference, "official_status": row.official_status},
    )
    return response


@onboarding_router.post(
    "/onboarding/cases/{case_id}/official-decision", response_model=OnboardingCaseResponse
)
async def record_official_decision(
    case_id: str,
    payload: OfficialDecisionRequest,
    request: Request,
    context: Annotated[
        AuthContext, Depends(require_permission(Permission.RECORD_OFFICIAL_DECISIONS))
    ],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingCaseResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).record_official_decision(
            _tenant_id(context),
            case_id,
            context.user.id,
            payload.decision,
            payload.evidence_reference,
            payload.message,
        )
    except OnboardingError as error:
        _raise(error)
    response = OnboardingCaseResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "onboarding.official.decision_recorded",
        "onboarding_case",
        row.id,
        {
            "official_status": row.official_status,
            "evidence_reference": row.official_evidence_reference,
        },
    )
    return response


@onboarding_router.get(
    "/onboarding/cases/{case_id}/readiness", response_model=OnboardingReadinessResponse
)
async def readiness(
    case_id: str,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ONBOARDING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingReadinessResponse:
    try:
        result = await OnboardingService(session).readiness(_tenant_id(context), case_id)
    except OnboardingError as error:
        _raise(error)
    return OnboardingReadinessResponse.model_validate(result)


@onboarding_router.get("/mini-programs", response_model=list[MiniProgramResponse])
async def list_mini_programs(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ONBOARDING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MiniProgramResponse]:
    rows = await OnboardingService(session).list_mini_programs(_tenant_id(context))
    return [MiniProgramResponse.model_validate(item) for item in rows]


@onboarding_router.post(
    "/mini-programs", response_model=MiniProgramResponse, status_code=status.HTTP_201_CREATED
)
async def create_mini_program(
    payload: MiniProgramCreate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MiniProgramResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).create_mini_program(
            _tenant_id(context), context.user.id, payload.model_dump()
        )
    except OnboardingError as error:
        _raise(error)
    response = MiniProgramResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "mini_program.created",
        "mini_program",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@onboarding_router.patch("/mini-programs/{mini_program_id}", response_model=MiniProgramResponse)
async def update_mini_program(
    mini_program_id: str,
    payload: MiniProgramUpdate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MiniProgramResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).update_mini_program(
            _tenant_id(context),
            mini_program_id,
            context.user.id,
            payload.version,
            payload.model_dump(exclude={"version"}, exclude_unset=True),
        )
    except OnboardingError as error:
        _raise(error)
    response = MiniProgramResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "mini_program.updated",
        "mini_program",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@onboarding_router.get(
    "/platform/mini-programs", response_model=list[PlatformMiniProgramResponse]
)
async def list_platform_mini_programs(
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PlatformMiniProgramResponse]:
    del context
    rows = await OnboardingService(session).list_platform_mini_programs()
    return [PlatformMiniProgramResponse.model_validate(item) for item in rows]


@onboarding_router.post(
    "/platform/mini-programs",
    response_model=PlatformMiniProgramResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_platform_mini_program(
    payload: PlatformMiniProgramCreate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlatformMiniProgramResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).create_platform_mini_program(
            context.user.id, payload.model_dump()
        )
    except OnboardingError as error:
        _raise(error)
    return PlatformMiniProgramResponse.model_validate(row)


@onboarding_router.patch(
    "/platform/mini-programs/{program_id}", response_model=PlatformMiniProgramResponse
)
async def update_platform_mini_program(
    program_id: str,
    payload: PlatformMiniProgramUpdate,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlatformMiniProgramResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).update_platform_mini_program(
            program_id,
            context.user.id,
            payload.version,
            payload.model_dump(exclude={"version"}, exclude_unset=True),
        )
    except OnboardingError as error:
        _raise(error)
    return PlatformMiniProgramResponse.model_validate(row)


@onboarding_router.get("/store-bindings", response_model=list[StoreBindingResponse])
async def list_store_bindings(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ONBOARDING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StoreBindingResponse]:
    rows = await OnboardingService(session).list_bindings(_tenant_id(context))
    return [StoreBindingResponse.model_validate(item) for item in rows]


@onboarding_router.post(
    "/store-bindings",
    response_model=StoreBindingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_store_binding(
    payload: StoreBindingCreate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoreBindingResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).create_binding(
            _tenant_id(context), context.user.id, payload.model_dump()
        )
    except OnboardingError as error:
        _raise(error)
    response = StoreBindingResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "store_binding.created",
        "store_binding",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@onboarding_router.patch("/store-bindings/{binding_id}", response_model=StoreBindingResponse)
async def update_store_binding(
    binding_id: str,
    payload: StoreBindingUpdate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoreBindingResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).update_binding(
            _tenant_id(context),
            binding_id,
            context.user.id,
            payload.version,
            payload.model_dump(exclude={"version"}, exclude_unset=True),
        )
    except OnboardingError as error:
        _raise(error)
    response = StoreBindingResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "store_binding.updated",
        "store_binding",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@onboarding_router.get("/position-services", response_model=list[PositionServiceResponse])
async def list_position_services(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ONBOARDING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PositionServiceResponse]:
    rows = await OnboardingService(session).list_mounts(_tenant_id(context))
    return [PositionServiceResponse.model_validate(item) for item in rows]


@onboarding_router.post(
    "/position-services",
    response_model=PositionServiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_position_service(
    payload: PositionServiceCreate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PositionServiceResponse:
    del csrf_context
    try:
        row = await OnboardingService(session).create_mount(
            _tenant_id(context), context.user.id, payload.model_dump()
        )
    except OnboardingError as error:
        _raise(error)
    response = PositionServiceResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "position_service.created",
        "position_service",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@onboarding_router.post(
    "/position-services/{mount_id}/transition", response_model=PositionServiceResponse
)
async def transition_position_service(
    mount_id: str,
    payload: PositionServiceTransition,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PositionServiceResponse:
    del csrf_context
    if payload.status in {"authorized", "mounted"} and not has_permission(
        context.role, Permission.RECORD_OFFICIAL_DECISIONS
    ):
        raise auth_error(
            "permission_denied",
            "只有总部管理员可以依据官方凭证记录授权或挂载成功",
            403,
        )
    try:
        row = await OnboardingService(session).transition_mount(
            _tenant_id(context),
            mount_id,
            context.user.id,
            payload.version,
            payload.status,
            payload.official_reference,
            payload.evidence_reference,
            payload.message,
        )
    except OnboardingError as error:
        _raise(error)
    response = PositionServiceResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "position_service.transitioned",
        "position_service",
        row.id,
        {"status": row.status, "official_reference": row.official_reference},
    )
    return response


__all__ = ["onboarding_router"]
