"""Validated request and response schemas for identity endpoints."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from poi_admin.core.permissions import Role

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("请输入有效的邮箱地址")
    return email


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)

    _normalize_email = field_validator("email")(normalize_email)


class TenantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("租户名称不能为空")
        return value

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        value = value.strip().casefold()
        if not SLUG_PATTERN.fullmatch(value):
            raise ValueError("租户标识只能包含小写字母、数字和连字符")
        return value


class TenantStatusUpdateRequest(BaseModel):
    status: Literal["active", "suspended"]


class InvitationCreateRequest(BaseModel):
    email: str
    role: Role
    expires_in_days: int = Field(default=7, ge=1, le=30)

    _normalize_email = field_validator("email")(normalize_email)


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=20)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("姓名不能为空")
        return value


class TenantSwitchRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=36)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    status: str
    is_platform_admin: bool


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    status: str


class MembershipResponse(BaseModel):
    id: str
    tenant_id: str
    tenant_name: str
    user_id: str
    email: str
    display_name: str
    role: Role
    status: str


class LoginResponse(BaseModel):
    user: UserResponse
    tenants: list[MembershipResponse]
    csrf_token: str


class MeResponse(BaseModel):
    user: UserResponse
    tenant: TenantResponse | None
    membership: MembershipResponse | None
    tenants: list[MembershipResponse] = Field(default_factory=list)


class InvitationResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    role: Role
    expires_at: datetime
    invite_token: str


class InvitationAcceptedResponse(BaseModel):
    user: UserResponse
    membership: MembershipResponse


__all__ = [
    "AcceptInvitationRequest",
    "InvitationAcceptedResponse",
    "InvitationCreateRequest",
    "InvitationResponse",
    "LoginRequest",
    "LoginResponse",
    "MeResponse",
    "MembershipResponse",
    "TenantCreateRequest",
    "TenantResponse",
    "TenantStatusUpdateRequest",
    "TenantSwitchRequest",
    "UserResponse",
    "normalize_email",
]
