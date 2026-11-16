"""Explicit root-only provisioning for an additional owner-approved platform admin.

Reads credentials only from stdin, never changes existing accounts, never exposes
an HTTP signup route, and leaves the first-admin bootstrap restrictions unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.audit.models import AuditLog
from poi_admin.core.config import get_settings
from poi_admin.core.database import create_database
from poi_admin.core.security import hash_password
from poi_admin.identity.models import Tenant, User
from poi_admin.identity.schemas import normalize_email

ORIGIN = "https://poi.zzybyzz6369.my.id"


class ProvisioningError(Exception):
    pass


async def create_additional_admin(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    confirm_global_admin: bool,
) -> User:
    if confirm_global_admin is not True:
        raise ProvisioningError("explicit_platform_admin_confirmation_required")
    email = normalize_email(email)
    if not 8 <= len(password) <= 256 or not 1 <= len(display_name.strip()) <= 120:
        raise ProvisioningError("invalid_account_details")
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(text("select pg_advisory_xact_lock(7804913257342)"))
    existing = (await session.scalars(select(User).order_by(User.id))).all()
    if any(user.email == email for user in existing):
        raise ProvisioningError("account_exists_no_changes_made")
    if not any(user.is_platform_admin and user.status == "active" for user in existing):
        raise ProvisioningError("first_admin_requires_bootstrap")
    before = {
        user.id: (user.password_hash, user.status, user.is_platform_admin, user.display_name)
        for user in existing
    }
    user = User(
        email=email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        status="active",
        is_platform_admin=True,
    )
    session.add(user)
    await session.flush()
    tenants = (await session.scalars(select(Tenant))).all()
    for tenant in tenants:
        session.add(
            AuditLog(
                tenant_id=tenant.id,
                actor_user_id=None,
                action="platform.admin_created_by_server_operator",
                resource_type="user",
                resource_id=user.id,
                after_summary={
                    "is_platform_admin": True,
                    "status": "active",
                    "provisioning_channel": "owner_approved_ssh",
                },
            )
        )
    for item in existing:
        assert before[item.id] == (
            item.password_hash,
            item.status,
            item.is_platform_admin,
            item.display_name,
        )
    await session.commit()
    await session.refresh(user)
    return user


async def verify_login(email: str, password: str) -> dict[str, object]:
    csrf = None
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        try:
            response = await client.post(
                ORIGIN + "/api/v1/auth/login", json={"email": email, "password": password}
            )
            if response.status_code != 200:
                raise ProvisioningError("login_verification_failed")
            result = response.json()
            csrf = result["csrf_token"]
            if not result["user"]["is_platform_admin"]:
                raise ProvisioningError("platform_role_verification_failed")
            me = await client.get(ORIGIN + "/api/v1/me")
            if me.status_code != 200 or not me.json()["user"]["is_platform_admin"]:
                raise ProvisioningError("session_verification_failed")
            listing = await client.get(ORIGIN + "/api/v1/platform/tenants")
            if listing.status_code != 200:
                raise ProvisioningError("platform_access_verification_failed")
            active = [item for item in listing.json() if item["status"] == "active"]
            for tenant in active:
                selected = await client.post(
                    ORIGIN + "/api/v1/auth/select-tenant",
                    headers={"X-CSRF-Token": csrf},
                    json={"tenant_id": tenant["id"]},
                )
                if selected.status_code != 200:
                    raise ProvisioningError("tenant_access_verification_failed")
                capabilities = await client.get(ORIGIN + "/api/v1/merchant-applyments/capabilities")
                if capabilities.status_code != 200:
                    raise ProvisioningError("applyment_access_verification_failed")
                if capabilities.json()["real_submission_enabled"]:
                    raise ProvisioningError("unexpected_real_submission_flag")
            return {
                "login_verified": True,
                "platform_management_verified": True,
                "accessible_merchant_spaces": len(active),
                "real_submission_enabled": False,
            }
        finally:
            if csrf:
                await client.post(ORIGIN + "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})


async def main() -> None:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise ProvisioningError("authorized_server_root_required")
    settings = get_settings()
    if settings.environment != "production" or settings.public_base_url != ORIGIN:
        raise ProvisioningError("unexpected_environment")
    payload = json.load(sys.stdin)
    database = create_database(settings)
    try:
        async with database.session_factory() as session:
            before = list((await session.scalars(select(User).order_by(User.id))).all())
            # Compare protected existing-account fields again in a fresh DB session after login.
            baseline = {
                item.id: hashlib.sha256(
                    repr(
                        (item.email, item.password_hash, item.status, item.is_platform_admin)
                    ).encode()
                ).hexdigest()
                for item in before
            }
            user = await create_additional_admin(session, **payload)
            print(
                json.dumps(
                    {
                        "account_created": True,
                        "email": user.email,
                        "display_name": user.display_name,
                        "platform_admin": True,
                    }
                ),
                flush=True,
            )
        verified = await verify_login(payload["email"], payload["password"])
        async with database.session_factory() as session:
            for user_id, digest in baseline.items():
                item = await session.get(User, user_id)
                assert item is not None
                current = hashlib.sha256(
                    repr(
                        (item.email, item.password_hash, item.status, item.is_platform_admin)
                    ).encode()
                ).hexdigest()
                if current != digest:
                    raise ProvisioningError("existing_account_changed")
        print(json.dumps({**verified, "existing_accounts_unchanged": True}), flush=True)
    finally:
        payload.clear()
        await database.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        code = str(error) if isinstance(error, ProvisioningError) else type(error).__name__
        print(json.dumps({"verification": "not_complete", "error_code": code}), flush=True)
        raise SystemExit(1) from None
