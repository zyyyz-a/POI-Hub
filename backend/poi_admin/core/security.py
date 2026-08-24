"""Password, opaque token, and browser cookie security helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Response

SESSION_COOKIE_NAME = "poi_session"
CSRF_COOKIE_NAME = "poi_csrf"
TENANT_COOKIE_NAME = "poi_tenant"

# Argon2id is the PasswordHasher default, but setting it explicitly documents the contract.
PASSWORD_HASHER = PasswordHasher()


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def new_opaque_token() -> str:
    """Create a high-entropy token suitable for a browser cookie."""

    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a session or invitation token before persistence."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""

    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password without leaking whether a hash is malformed."""

    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def set_auth_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
    *,
    secure: bool,
    max_age: int,
) -> None:
    """Set the HttpOnly session cookie and JS-readable CSRF cookie."""

    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=max_age,
        secure=secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        secure=secure,
        httponly=False,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response, *, secure: bool) -> None:
    """Remove authentication cookies from a browser response."""

    for name in (SESSION_COOKIE_NAME, CSRF_COOKIE_NAME, TENANT_COOKIE_NAME):
        response.delete_cookie(name, secure=secure, samesite="lax", path="/")


__all__ = [
    "CSRF_COOKIE_NAME",
    "PASSWORD_HASHER",
    "SESSION_COOKIE_NAME",
    "TENANT_COOKIE_NAME",
    "clear_auth_cookies",
    "hash_password",
    "hash_token",
    "new_opaque_token",
    "set_auth_cookies",
    "utcnow",
    "verify_password",
]
