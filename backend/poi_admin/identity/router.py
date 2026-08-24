"""HTTP routes for authentication, invitations, tenants, and members."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.audit.service import AuditService
from poi_admin.core.config import Settings
from poi_admin.core.database import get_session
from poi_admin.core.dependencies import (
    AuthContext,
    auth_error,
    get_auth_context,
    require_csrf,
    require_permission,
)
from poi_admin.core.permissions import Permission, Role
from poi_admin.core.security import (
    CSRF_COOKIE_NAME,
    TENANT_COOKIE_NAME,
    clear_auth_cookies,
    set_auth_cookies,
)

from .models import Tenant
from .schemas import (
    AcceptInvitationRequest,
    InvitationAcceptedResponse,
    InvitationCreateRequest,
    InvitationResponse,
    LoginRequest,
    LoginResponse,
    MembershipResponse,
    MeResponse,
    TenantCreateRequest,
    TenantResponse,
    TenantStatusUpdateRequest,
    TenantSwitchRequest,
    UserResponse,
)
from .service import IdentityService, IdentityServiceError

identity_router = APIRouter(tags=["identity"])


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _secure_cookies(settings: Settings) -> bool:
    return settings.environment not in {"local", "test"}


def _user_response(user: Any) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        is_platform_admin=user.is_platform_admin,
    )


def _membership_response(membership: Any) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        tenant_id=membership.tenant_id,
        tenant_name=membership.tenant.name,
        user_id=membership.user_id,
        email=membership.user.email,
        display_name=membership.user.display_name,
        role=membership.role,
        status=membership.status,
    )


def _raise_identity_error(error: IdentityServiceError) -> None:
    raise auth_error(error.code, error.message, error.status_code)


@identity_router.post("/auth/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    service = IdentityService(session)
    try:
        result = await service.authenticate(
            payload.email,
            payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except IdentityServiceError as error:
        _raise_identity_error(error)
    max_age = int((result.session.expires_at - result.session.created_at).total_seconds())
    set_auth_cookies(
        response,
        result.session_token,
        result.csrf_token,
        secure=_secure_cookies(_settings(request)),
        max_age=max_age,
    )
    return LoginResponse(
        user=_user_response(result.user),
        tenants=[_membership_response(item) for item in result.memberships],
        csrf_token=result.csrf_token,
    )


@identity_router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await IdentityService(session).revoke_session(context.session)
    clear_auth_cookies(response, secure=_secure_cookies(_settings(request)))
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@identity_router.get("/auth/csrf")
async def csrf_token(
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    token = await IdentityService(session).rotate_csrf(context.session)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        secure=_secure_cookies(_settings(request)),
        httponly=False,
        samesite="lax",
        path="/",
    )
    return {"csrf_token": token}


async def me(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeResponse:
    tenant = TenantResponse.model_validate(context.tenant) if context.tenant else None
    membership = _membership_response(context.membership) if context.membership else None
    memberships = await IdentityService(session).memberships_for_user(context.user.id)
    return MeResponse(
        user=_user_response(context.user),
        tenant=tenant,
        membership=membership,
        tenants=[_membership_response(item) for item in memberships],
    )


identity_router.add_api_route("/me", me, methods=["GET"], response_model=MeResponse)
identity_router.add_api_route("/auth/me", me, methods=["GET"], response_model=MeResponse)


@identity_router.post("/auth/select-tenant", response_model=MeResponse)
async def select_tenant(
    payload: TenantSwitchRequest,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeResponse:
    service = IdentityService(session)
    tenant = await service.tenant_by_id(payload.tenant_id)
    if tenant is None or tenant.status != "active":
        raise auth_error("tenant_not_found", "租户不存在或已停用", 404)
    membership = next(
        (
            item
            for item in await service.memberships_for_user(context.user.id)
            if item.tenant_id == tenant.id
        ),
        None,
    )
    if membership is None and not context.user.is_platform_admin:
        raise auth_error("tenant_access_denied", "无权访问该租户", 403)
    response.set_cookie(
        "poi_tenant",
        tenant.id,
        secure=_secure_cookies(_settings(request)),
        samesite="lax",
        path="/",
    )
    return MeResponse(
        user=_user_response(context.user),
        tenant=TenantResponse.model_validate(tenant),
        membership=_membership_response(membership) if membership else None,
    )


@identity_router.post(
    "/platform/tenants", status_code=status.HTTP_201_CREATED, response_model=TenantResponse
)
async def create_tenant(
    payload: TenantCreateRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantResponse:
    del csrf_context
    try:
        tenant = await IdentityService(session).create_tenant(
            context.user, name=payload.name, slug=payload.slug
        )
    except IdentityServiceError as error:
        _raise_identity_error(error)
    return TenantResponse.model_validate(tenant)


@identity_router.get("/platform/tenants", response_model=list[TenantResponse])
async def list_tenants(
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TenantResponse]:
    del context
    tenants = (await session.execute(select(Tenant).order_by(Tenant.created_at))).scalars().all()
    return [TenantResponse.model_validate(item) for item in tenants]


@identity_router.patch("/platform/tenants/{tenant_id}/status", response_model=TenantResponse)
async def update_tenant_status(
    tenant_id: str,
    payload: TenantStatusUpdateRequest,
    response: Response,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_TENANTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantResponse:
    """Let the central control plane suspend or restore one merchant tenant."""

    del csrf_context
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    ).scalar_one_or_none()
    if tenant is None:
        raise auth_error("tenant_not_found", "租户不存在", status.HTTP_404_NOT_FOUND)
    before_status = tenant.status
    if before_status == payload.status:
        return TenantResponse.model_validate(tenant)

    tenant.status = payload.status
    await session.flush()
    await AuditService(session).record(
        tenant_id=tenant.id,
        actor_user_id=context.user.id,
        action="platform.tenant_status_updated",
        resource_type="tenant",
        resource_id=tenant.id,
        before={"status": before_status},
        after={"status": tenant.status},
        correlation_id=getattr(request.state, "request_id", None),
    )
    if payload.status == "suspended" and context.tenant_id == tenant.id:
        response.delete_cookie(TENANT_COOKIE_NAME, path="/")
    return TenantResponse.model_validate(tenant)


@identity_router.post(
    "/members/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationResponse,
)
async def create_invitation(
    payload: InvitationCreateRequest,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_MEMBERS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InvitationResponse:
    del csrf_context
    if context.tenant is None:
        raise auth_error("tenant_required", "请先选择租户", 400)
    try:
        invitation, token = await IdentityService(session).create_invitation(
            context.user,
            tenant_id=context.tenant.id,
            email=payload.email,
            role=payload.role,
            expires_in_days=payload.expires_in_days,
        )
    except IdentityServiceError as error:
        _raise_identity_error(error)
    return InvitationResponse(
        id=invitation.id,
        tenant_id=invitation.tenant_id,
        email=invitation.email,
        role=Role(invitation.role),
        expires_at=invitation.expires_at,
        invite_token=token,
    )


@identity_router.get("/members", response_model=list[MembershipResponse])
async def list_members(
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_MEMBERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MembershipResponse]:
    if context.tenant is None:
        raise auth_error("tenant_required", "请先选择租户", 400)
    members = await IdentityService(session).list_members(context.tenant.id)
    return [_membership_response(item) for item in members]


@identity_router.post(
    "/invitations/accept",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationAcceptedResponse,
)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InvitationAcceptedResponse:
    try:
        result = await IdentityService(session).accept_invitation(
            payload.token, password=payload.password, display_name=payload.display_name
        )
    except IdentityServiceError as error:
        _raise_identity_error(error)
    await session.refresh(result.membership, ["tenant", "user"])
    return InvitationAcceptedResponse(
        user=_user_response(result.user),
        membership=_membership_response(result.membership),
    )


__all__ = ["identity_router"]
