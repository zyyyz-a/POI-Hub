"""One-time, production-safe platform administrator bootstrap."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.config import Settings, get_settings
from poi_admin.core.database import create_database
from poi_admin.core.security import hash_password, utcnow
from poi_admin.identity.models import User, UserSession
from poi_admin.identity.schemas import normalize_email

MIN_BOOTSTRAP_PASSWORD_LENGTH = 16
MAX_BOOTSTRAP_PASSWORD_LENGTH = 256
_POSTGRES_BOOTSTRAP_LOCK_ID = 7_804_913_257_341


class BootstrapError(Exception):
    """A safe failure that can be printed by the one-time bootstrap CLI."""


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    action: Literal["created", "promoted", "rotated"]
    user_id: str
    email: str


def validate_bootstrap_password(password: str) -> str:
    if len(password) < MIN_BOOTSTRAP_PASSWORD_LENGTH:
        raise BootstrapError(
            f"password must be at least {MIN_BOOTSTRAP_PASSWORD_LENGTH} characters"
        )
    if len(password) > MAX_BOOTSTRAP_PASSWORD_LENGTH:
        raise BootstrapError(
            f"password must be at most {MAX_BOOTSTRAP_PASSWORD_LENGTH} characters"
        )
    return password


async def bootstrap_platform_admin(
    session: AsyncSession,
    *,
    email: str,
    display_name: str,
    password: str,
    promote_existing: bool = False,
    rotate_existing: bool = False,
) -> BootstrapResult:
    """Create the first platform admin or explicitly recover that same account.

    The default path refuses to run once any platform administrator exists. This
    keeps a leaked deployment command from silently minting another global admin.
    PostgreSQL deployments also take a transaction advisory lock so two bootstrap
    jobs cannot both pass the empty-table check.
    """

    normalized_email = normalize_email(email)
    cleaned_name = display_name.strip()
    if not cleaned_name:
        raise BootstrapError("display name cannot be empty")
    if len(cleaned_name) > 120:
        raise BootstrapError("display name must be at most 120 characters")
    password = validate_bootstrap_password(password)
    if promote_existing and rotate_existing:
        raise BootstrapError("choose either promote-existing or rotate-existing")

    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    async with transaction:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": _POSTGRES_BOOTSTRAP_LOCK_ID},
            )

        platform_admins = list(
            (
                await session.execute(
                    select(User).where(User.is_platform_admin.is_(True)).with_for_update()
                )
            )
            .scalars()
            .all()
        )
        target = (
            await session.execute(
                select(User).where(User.email == normalized_email).with_for_update()
            )
        ).scalar_one_or_none()

        if rotate_existing:
            if target is None or not target.is_platform_admin:
                raise BootstrapError("the requested platform admin does not exist")
            target.display_name = cleaned_name
            target.password_hash = hash_password(password)
            target.status = "active"
            await session.execute(
                update(UserSession)
                .where(UserSession.user_id == target.id, UserSession.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            action: Literal["created", "promoted", "rotated"] = "rotated"
        elif platform_admins:
            raise BootstrapError(
                "a platform admin already exists; use authenticated administration or "
                "--rotate-existing for that same account"
            )
        elif target is not None:
            if not promote_existing:
                raise BootstrapError(
                    "the email already belongs to a non-admin user; pass --promote-existing "
                    "only after verifying that account"
                )
            target.display_name = cleaned_name
            target.password_hash = hash_password(password)
            target.status = "active"
            target.is_platform_admin = True
            action = "promoted"
        else:
            target = User(
                email=normalized_email,
                display_name=cleaned_name,
                password_hash=hash_password(password),
                status="active",
                is_platform_admin=True,
            )
            session.add(target)
            await session.flush()
            action = "created"

    return BootstrapResult(action=action, user_id=target.id, email=target.email)


def _read_password(*, password_stdin: bool) -> str:
    if password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise BootstrapError("password stdin was empty")
        return validate_bootstrap_password(password)
    if not sys.stdin.isatty():
        raise BootstrapError("interactive terminal required unless --password-stdin is used")
    password = getpass.getpass("Platform admin password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise BootstrapError("password confirmation does not match")
    return validate_bootstrap_password(password)


async def _run(args: argparse.Namespace, settings: Settings) -> BootstrapResult:
    database = create_database(settings)
    try:
        async with database.session_factory() as session:
            return await bootstrap_platform_admin(
                session,
                email=args.email,
                display_name=args.display_name,
                password=_read_password(password_stdin=args.password_stdin),
                promote_existing=args.promote_existing,
                rotate_existing=args.rotate_existing,
            )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the first POI Hub platform administrator safely."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", default="平台管理员")
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read one password line from stdin; avoids exposing it in the process list",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--promote-existing", action="store_true")
    mode.add_argument("--rotate-existing", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(args, get_settings()))
    except (BootstrapError, ValueError) as error:
        parser.exit(2, f"bootstrap failed: {error}\n")
    print(f"platform admin {result.action}: {result.email}")


if __name__ == "__main__":
    main()


__all__ = [
    "BootstrapError",
    "BootstrapResult",
    "bootstrap_platform_admin",
    "main",
    "validate_bootstrap_password",
]

