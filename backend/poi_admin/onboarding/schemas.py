"""API contracts for qualification, filing, mini-program, and position services."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QualificationItem(BaseModel):
    code: str = Field(min_length=2, max_length=100)
    label: str = Field(min_length=1, max_length=160)
    required: bool = True
    present: bool = False
    verified: bool = False
    expires_on: date | None = None
    evidence_reference: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)


class OnboardingCaseCreate(BaseModel):
    store_id: str = Field(min_length=1)
    route: Literal["wechat_location_miniprogram", "wechat_shop_local_life"] = (
        "wechat_location_miniprogram"
    )
    category_code: str = Field(min_length=1, max_length=100)
    category_name: str = Field(min_length=1, max_length=160)
    subject_type: Literal["individual_business", "enterprise"]
    region_code: str | None = Field(default=None, max_length=32)
    requirements: list[QualificationItem] = Field(default_factory=list, max_length=100)


class OnboardingCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    store_id: str
    route: str
    category_code: str
    category_name: str
    subject_type: str
    region_code: str | None
    stage: str
    status: str
    requirements: list[dict[str, Any]]
    precheck_status: str
    precheck_report: dict[str, Any]
    official_status: str
    official_reference: str | None
    official_evidence_reference: str | None
    official_submitted_at: datetime | None
    official_decided_at: datetime | None
    position_status: str
    blocker_code: str | None
    blocker_message: str | None
    next_action: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class PrecheckRequest(BaseModel):
    items: list[QualificationItem] = Field(min_length=1, max_length=100)
    rule_source_reference: str = Field(min_length=1, max_length=500)


class OfficialSubmissionRequest(BaseModel):
    official_reference: str = Field(min_length=1, max_length=200)
    evidence_reference: str = Field(min_length=1, max_length=500)


class OfficialDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "paused", "needs_more_info"]
    evidence_reference: str = Field(min_length=1, max_length=500)
    message: str | None = Field(default=None, max_length=500)


class MiniProgramCreate(BaseModel):
    connection_id: str | None = Field(default=None, max_length=36)
    name: str = Field(min_length=1, max_length=160)
    app_id: str | None = Field(default=None, max_length=128)
    owner_subject: str = Field(min_length=1, max_length=200)
    ownership_mode: Literal["merchant_owned", "platform_owned"] = "merchant_owned"
    authorization_reference: str | None = Field(default=None, max_length=500)
    payment_merchant_id: str | None = Field(default=None, max_length=128)
    payment_owner_verified: bool = False
    video_channel_id: str | None = Field(default=None, max_length=160)
    callback_configured: bool = False


class MiniProgramUpdate(BaseModel):
    connection_id: str | None = Field(default=None, max_length=36)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    app_id: str | None = Field(default=None, max_length=128)
    authorization_reference: str | None = Field(default=None, max_length=500)
    payment_merchant_id: str | None = Field(default=None, max_length=128)
    payment_owner_verified: bool | None = None
    video_channel_id: str | None = Field(default=None, max_length=160)
    callback_configured: bool | None = None
    status: Literal["draft", "authorized", "active", "suspended"] | None = None
    location_service_status: (
        Literal["not_configured", "configured", "authorization_pending", "authorized"] | None
    ) = None
    version: int = Field(ge=1)


class MiniProgramResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str | None
    name: str
    app_id: str | None
    owner_subject: str
    ownership_mode: str
    status: str
    authorization_reference: str | None
    payment_merchant_id: str | None
    payment_owner_verified: bool
    video_channel_id: str | None
    location_service_status: str
    callback_configured: bool
    version: int
    created_at: datetime
    updated_at: datetime


class PositionServiceCreate(BaseModel):
    onboarding_case_id: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    service_poi_id: str | None = None
    mini_program_id: str = Field(min_length=1)
    service_type: Literal["group_buying", "reservation", "preorder", "pickup", "delivery"]
    service_name: str = Field(min_length=1, max_length=80)
    entry_path: str = Field(min_length=1, max_length=500)

    @field_validator("entry_path")
    @classmethod
    def validate_entry_path(cls, value: str) -> str:
        if value.startswith(("http://", "https://", "javascript:")):
            raise ValueError("小程序入口必须是内部页面路径，不能是外部 URL")
        return value.lstrip("/")


class PositionServiceTransition(BaseModel):
    status: Literal[
        "service_defined",
        "authorization_pending",
        "authorized",
        "mounted",
        "rejected",
        "unmounted",
    ]
    official_reference: str | None = Field(default=None, max_length=200)
    evidence_reference: str | None = Field(default=None, max_length=500)
    message: str | None = Field(default=None, max_length=500)
    version: int = Field(ge=1)


class PositionServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    onboarding_case_id: str
    store_id: str
    service_poi_id: str | None
    mini_program_id: str
    service_type: str
    service_name: str
    entry_path: str
    status: str
    official_reference: str | None
    evidence_reference: str | None
    last_error: str | None
    authorized_at: datetime | None
    mounted_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class OnboardingReadinessResponse(BaseModel):
    case_id: str
    ready: bool
    blockers: list[str]
    checks: dict[str, bool]


__all__ = [
    "MiniProgramCreate",
    "MiniProgramResponse",
    "MiniProgramUpdate",
    "OfficialDecisionRequest",
    "OfficialSubmissionRequest",
    "OnboardingCaseCreate",
    "OnboardingCaseResponse",
    "OnboardingReadinessResponse",
    "PositionServiceCreate",
    "PositionServiceResponse",
    "PositionServiceTransition",
    "PrecheckRequest",
    "QualificationItem",
]
