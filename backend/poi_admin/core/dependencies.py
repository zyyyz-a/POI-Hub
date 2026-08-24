"""FastAPI dependencies for authenticated sessions and tenant-scoped policies."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from poi_admin.identity.models import Membership, Tenant, User, UserSession

from .database import get_session
from .permissions import Permission, Role, has_permission
from .security import SESSION_COOKIE_NAME, TENANT_COOKIE_NAME, hash_token, utcnow

SESSION_TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(slots=True)
class AuthContext:
    """Authenticated principal and its explicitly selected tenant context."""

    user: User
    session: UserSession
    tenant: Tenant | None
    membership: Membership | None
    role: Role | None

    @property
    def tenant_id(self) -> str | None:
        return self.tenant.id if self.tenant is not None else None


def auth_error(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def get_auth_context(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthContext:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise auth_error("authentication_required", "请先登录", status.HTTP_401_UNAUTHORIZED)

    auth_session = (
        await session.execute(
            select(UserSession)
            .where(UserSession.token_hash == hash_token(token))
            .options(selectinload(UserSession.user))
        )
    ).scalar_one_or_none()
    if auth_session is None or auth_session.revoked_at is not None:
        raise auth_error("authentication_required", "登录会话无效", status.HTTP_401_UNAUTHORIZED)
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= utcnow():
        raise auth_error("session_expired", "登录会话已过期", status.HTTP_401_UNAUTHORIZED)
    user = auth_session.user
    if user is None or user.status != "active":
        raise auth_error("authentication_required", "用户已停用", status.HTTP_401_UNAUTHORIZED)

    now = utcnow()
    last_seen_at = auth_session.last_seen_at
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=UTC)
    should_touch_session = last_seen_at <= now - SESSION_TOUCH_INTERVAL
    if should_touch_session:
        auth_session.last_seen_at = now
    tenant_id = request.headers.get("X-Tenant-ID") or request.cookies.get(TENANT_COOKIE_NAME)
    tenant: Tenant | None = None
    membership: Membership | None = None
    role: Role | None = Role.PLATFORM_ADMIN if user.is_platform_admin else None

    if tenant_id:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None or tenant.status != "active":
            raise auth_error("tenant_not_found", "租户不存在或已停用", status.HTTP_404_NOT_FOUND)
        membership = (
            await session.execute(
                select(Membership)
                .where(
                    Membership.tenant_id == tenant_id,
                    Membership.user_id == user.id,
                    Membership.status == "active",
                )
                .options(selectinload(Membership.tenant), selectinload(Membership.user))
            )
        ).scalar_one_or_none()
        if membership is None and not user.is_platform_admin:
            raise auth_error("tenant_access_denied", "无权访问该租户", status.HTTP_403_FORBIDDEN)
        if membership is not None and not user.is_platform_admin:
            role = (
                Role(membership.role) if membership.role in {item.value for item in Role} else None
            )
    elif not user.is_platform_admin:
        memberships = list(
            (await session.execute(
                select(Membership)
                .where(Membership.user_id == user.id, Membership.status == "active")
                .options(selectinload(Membership.tenant), selectinload(Membership.user))
                .order_by(Membership.created_at)
            )).scalars().all()
        )
        membership = memberships[0] if len(memberships) == 1 else None
        if membership is not None:
            tenant = membership.tenant
            role = (
                Role(membership.role) if membership.role in {item.value for item in Role} else None
            )

    if should_touch_session:
        await session.commit()
    context = AuthContext(user, auth_session, tenant, membership, role)
    request.state.auth_context = context
    return context


async def require_csrf(
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    """Require a CSRF header matching the hash kept with the session."""

    supplied = request.headers.get("X-CSRF-Token")
    if not supplied or not secrets.compare_digest(
        hash_token(supplied), context.session.csrf_token_hash
    ):
        raise auth_error("csrf_failed", "缺少或无效的 CSRF 令牌", status.HTTP_403_FORBIDDEN)
    return context


def require_permission(permission: Permission) -> Callable[..., Awaitable[AuthContext]]:
    """Build a dependency enforcing one fixed backend permission."""

    async def dependency(
        context: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> AuthContext:
        if not has_permission(context.role, permission):
            raise auth_error(
                "permission_denied", "当前角色无权执行此操作", status.HTTP_403_FORBIDDEN
            )
        return context

    return dependency


def require_tenant_permission(
    permission: Permission,
) -> Callable[..., Awaitable[AuthContext]]:
    """Require an explicitly selected tenant before checking a tenant permission."""

    async def dependency(
        context: Annotated[AuthContext, Depends(require_tenant)],
    ) -> AuthContext:
        if not has_permission(context.role, permission):
            raise auth_error(
                "permission_denied", "当前角色无权执行此操作", status.HTTP_403_FORBIDDEN
            )
        return context

    return dependency


async def require_tenant(
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    """Require a selected tenant, independently of a specific role."""

    if context.tenant is None:
        raise auth_error("tenant_required", "请先选择租户", status.HTTP_400_BAD_REQUEST)
    return context


__all__ = [
    "AuthContext",
    "auth_error",
    "get_auth_context",
    "require_csrf",
    "require_permission",
    "require_tenant_permission",
    "require_tenant",
]
