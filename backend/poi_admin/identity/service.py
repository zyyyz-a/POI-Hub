"""Application services for invitation-only authentication and tenancy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from poi_admin.core.permissions import Role
from poi_admin.core.security import (
    hash_password,
    hash_token,
    new_opaque_token,
    utcnow,
    verify_password,
)

from .models import Invitation, Membership, Tenant, User, UserSession
from .schemas import normalize_email

SESSION_TTL = timedelta(hours=12)


class IdentityServiceError(Exception):
    """A safe, user-facing identity operation error."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class LoginResult:
    user: User
    session: UserSession
    session_token: str
    csrf_token: str
    memberships: list[Membership]


@dataclass(slots=True)
class AcceptedInvitation:
    user: User
    membership: Membership


def _aware(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive datetime values for comparisons."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class IdentityService:
    """Persistence boundary for auth, membership, and invitation workflows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def authenticate(
        self,
        email: str,
        password: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> LoginResult:
        normalized = normalize_email(email)
        user = (
            await self.session.execute(select(User).where(User.email == normalized))
        ).scalar_one_or_none()
        if (
            user is None
            or user.status != "active"
            or not verify_password(user.password_hash, password)
        ):
            raise IdentityServiceError("invalid_credentials", "邮箱或密码不正确", 401)

        now = utcnow()
        session_token = new_opaque_token()
        csrf_token = new_opaque_token()
        auth_session = UserSession(
            user_id=user.id,
            token_hash=hash_token(session_token),
            csrf_token_hash=hash_token(csrf_token),
            expires_at=now + SESSION_TTL,
            last_seen_at=now,
            user_agent=(user_agent or "")[:512] or None,
            ip_address=(ip_address or "")[:64] or None,
        )
        user.last_login_at = now
        self.session.add(auth_session)
        await self.session.commit()
        await self.session.refresh(user)
        memberships = await self.memberships_for_user(user.id)
        return LoginResult(user, auth_session, session_token, csrf_token, memberships)

    async def memberships_for_user(self, user_id: str) -> list[Membership]:
        result = await self.session.execute(
            select(Membership)
            .where(Membership.user_id == user_id, Membership.status == "active")
            .options(selectinload(Membership.tenant), selectinload(Membership.user))
            .order_by(Membership.created_at)
        )
        return list(result.scalars().all())

    async def create_tenant(self, actor: User, *, name: str, slug: str) -> Tenant:
        tenant = Tenant(
            name=name.strip(), slug=slug.strip().casefold(), created_by_user_id=actor.id
        )
        self.session.add(tenant)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise IdentityServiceError("tenant_slug_exists", "租户标识已存在", 409) from exc
        await self.session.refresh(tenant)
        return tenant

    async def tenant_by_id(self, tenant_id: str) -> Tenant | None:
        return (
            await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()

    async def create_invitation(
        self,
        actor: User,
        *,
        tenant_id: str,
        email: str,
        role: Role,
        expires_in_days: int = 7,
    ) -> tuple[Invitation, str]:
        tenant = await self.tenant_by_id(tenant_id)
        if tenant is None or tenant.status != "active":
            raise IdentityServiceError("tenant_not_found", "租户不存在或已停用", 404)
        if role == Role.PLATFORM_ADMIN:
            raise IdentityServiceError("invalid_invitation_role", "不能通过租户邀请平台管理员", 422)
        if not actor.is_platform_admin:
            membership = (
                await self.session.execute(
                    select(Membership).where(
                        Membership.tenant_id == tenant_id,
                        Membership.user_id == actor.id,
                        Membership.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if membership is None or membership.role != Role.TENANT_ADMIN.value:
                raise IdentityServiceError("permission_denied", "无权管理租户成员", 403)

        token = new_opaque_token()
        invitation = Invitation(
            tenant_id=tenant_id,
            email=normalize_email(email),
            role=role.value,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(days=expires_in_days),
            invited_by_user_id=actor.id,
        )
        self.session.add(invitation)
        await self.session.commit()
        await self.session.refresh(invitation)
        return invitation, token

    async def accept_invitation(
        self,
        token: str,
        *,
        password: str,
        display_name: str,
    ) -> AcceptedInvitation:
        invitation = (
            await self.session.execute(
                select(Invitation)
                .where(Invitation.token_hash == hash_token(token))
                .options(selectinload(Invitation.tenant))
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise IdentityServiceError("invalid_invitation", "邀请链接无效", 400)
        if invitation.accepted_at is not None:
            raise IdentityServiceError("invitation_used", "邀请链接已使用", 409)
        if _aware(invitation.expires_at) <= utcnow():
            raise IdentityServiceError("invitation_expired", "邀请链接已过期", 410)
        if invitation.tenant is None or invitation.tenant.status != "active":
            raise IdentityServiceError("tenant_inactive", "租户已停用或不存在", 403)

        email = normalize_email(invitation.email)
        user = (
            await self.session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                display_name=display_name.strip(),
                password_hash=hash_password(password),
                status="active",
            )
            self.session.add(user)
            await self.session.flush()
        elif user.status != "active":
            raise IdentityServiceError("user_inactive", "该用户已停用", 403)

        membership = (
            await self.session.execute(
                select(Membership).where(
                    Membership.tenant_id == invitation.tenant_id,
                    Membership.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            membership = Membership(
                tenant_id=invitation.tenant_id,
                user_id=user.id,
                role=invitation.role,
                status="active",
            )
            self.session.add(membership)
        else:
            membership.role = invitation.role
            membership.status = "active"
        invitation.accepted_at = utcnow()
        invitation.accepted_user_id = user.id
        await self.session.commit()
        await self.session.refresh(user)
        await self.session.refresh(membership)
        await self.session.refresh(membership, ["tenant", "user"])
        return AcceptedInvitation(user, membership)

    async def list_members(self, tenant_id: str) -> list[Membership]:
        result = await self.session.execute(
            select(Membership)
            .where(Membership.tenant_id == tenant_id)
            .options(selectinload(Membership.tenant), selectinload(Membership.user))
            .order_by(Membership.created_at)
        )
        return list(result.scalars().all())

    async def revoke_session(self, auth_session: UserSession) -> None:
        auth_session.revoked_at = utcnow()
        await self.session.commit()

    async def rotate_csrf(self, auth_session: UserSession) -> str:
        token = new_opaque_token()
        auth_session.csrf_token_hash = hash_token(token)
        await self.session.commit()
        return token


async def ensure_test_identity(session: AsyncSession) -> None:
    """Create deterministic local test users without enabling public signup."""

    admin = (
        await session.execute(select(User).where(User.email == "admin@example.com"))
    ).scalar_one_or_none()
    if admin is None:
        admin = User(
            email="admin@example.com",
            display_name="平台管理员",
            password_hash=hash_password("correct-horse-battery-staple"),
            is_platform_admin=True,
        )
        session.add(admin)
        await session.flush()
    else:
        admin.is_platform_admin = True

    tenant = (
        await session.execute(select(Tenant).where(Tenant.slug == "demo"))
    ).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name="演示租户", slug="demo", created_by_user_id=admin.id)
        session.add(tenant)
        await session.flush()

    operator = (
        await session.execute(select(User).where(User.email == "operator@example.com"))
    ).scalar_one_or_none()
    if operator is None:
        operator = User(
            email="operator@example.com",
            display_name="演示运营员",
            password_hash=hash_password("operator-password"),
        )
        session.add(operator)
        await session.flush()
    membership = (
        await session.execute(
            select(Membership).where(
                Membership.tenant_id == tenant.id, Membership.user_id == operator.id
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        session.add(Membership(tenant_id=tenant.id, user_id=operator.id, role=Role.OPERATOR.value))
    await session.commit()


__all__ = [
    "AcceptedInvitation",
    "IdentityService",
    "IdentityServiceError",
    "LoginResult",
    "SESSION_TTL",
    "ensure_test_identity",
]
