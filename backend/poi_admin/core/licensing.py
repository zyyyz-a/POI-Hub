"""Offline signed licenses for customer-owned appliance deployments."""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings


class LicenseClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    license_id: str = Field(min_length=1, max_length=120)
    customer_id: str = Field(min_length=1, max_length=120)
    customer_name: str = Field(min_length=1, max_length=200)
    installation_id: str = Field(min_length=1, max_length=120)
    issued_at: datetime
    expires_at: datetime
    max_stores: int = Field(ge=1, le=1_000_000)
    features: list[str] = Field(default_factory=list, max_length=100)


@dataclass(frozen=True, slots=True)
class LicenseState:
    mode: str
    status: Literal["disabled", "valid", "missing", "invalid", "expired"]
    claims: LicenseClaims | None = None
    error: str | None = None

    def current_status(self, now: datetime | None = None) -> str:
        if self.status != "valid" or self.claims is None:
            return self.status
        resolved_now = now or datetime.now(UTC)
        expires_at = _aware(self.claims.expires_at)
        return "expired" if expires_at <= resolved_now else "valid"

    def allows_writes(self, now: datetime | None = None) -> bool:
        return self.mode != "enforce" or self.current_status(now) == "valid"


def canonical_claims(claims: LicenseClaims | dict[str, Any]) -> bytes:
    value = (
        claims.model_dump(mode="json")
        if isinstance(claims, LicenseClaims)
        else LicenseClaims.model_validate(claims).model_dump(mode="json")
    )
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def load_license(settings: Settings) -> LicenseState:
    if settings.license_mode == "off":
        return LicenseState(mode="off", status="disabled")
    if not settings.license_path.is_file():
        return LicenseState(settings.license_mode, "missing", error="license_file_missing")
    try:
        envelope = json.loads(settings.license_path.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict):
            raise ValueError("license envelope must be an object")
        claims = LicenseClaims.model_validate(envelope.get("claims"))
        if claims.installation_id != settings.installation_id:
            raise ValueError("license installation does not match this appliance")
        signature = base64.b64decode(str(envelope.get("signature", "")), validate=True)
        public_key_bytes = base64.b64decode(settings.license_public_key, validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature, canonical_claims(claims))
    except (
        InvalidSignature,
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        ValidationError,
    ) as error:
        return LicenseState(settings.license_mode, "invalid", error=type(error).__name__)
    state = LicenseState(settings.license_mode, "valid", claims=claims)
    if state.current_status() == "expired":
        return LicenseState(settings.license_mode, "expired", claims=claims)
    return state


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def license_enforcement_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    state: LicenseState = request.app.state.license
    status = state.current_status()
    is_mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    exempt = request.url.path.startswith(
        (
            "/api/v1/auth/",
            "/api/v1/health/",
            "/api/v1/license/",
            "/api/v1/callbacks/",
            "/api/v1/invitations/accept",
        )
    )
    if state.mode == "enforce" and status != "valid" and is_mutation and not exempt:
        return JSONResponse(
            status_code=402,
            content={
                "code": "license_write_disabled",
                "message": "软件服务授权无效或已到期，当前仅允许查看和导出数据",
                "license_status": status,
            },
        )
    response = await call_next(request)
    if state.mode == "warn" and status not in {"valid", "disabled"}:
        response.headers["X-License-Warning"] = status
    return response


__all__ = [
    "LicenseClaims",
    "LicenseState",
    "canonical_claims",
    "license_enforcement_middleware",
    "load_license",
]
