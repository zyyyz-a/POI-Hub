"""Only individual businesses with the proprietor as administrator are accepted."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .limits import MAX_IMAGE_BYTES


class IndividualFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    merchant_name: str = Field(default="", max_length=128)
    license_number: str = Field(default="", max_length=18)
    license_address: str = Field(default="", max_length=512)
    license_period_begin: str = Field(default="", max_length=10)
    license_period_end: str = Field(default="", max_length=10)
    owner_name: str = Field(default="", max_length=100)
    id_number: str = Field(default="", max_length=18)
    id_period_begin: str = Field(default="", max_length=10)
    id_period_end: str = Field(default="", max_length=10)
    mobile_phone: str = Field(default="", max_length=32)
    contact_email: str = Field(default="", max_length=128)
    merchant_shortname: str = Field(default="", max_length=30)
    service_phone: str = Field(default="", max_length=32)
    store_name: str = Field(default="", max_length=128)
    store_address: str = Field(default="", max_length=512)
    store_area_code: str = Field(default="", max_length=6)
    bank_account_type: Literal["personal", "corporate"] = "personal"
    account_bank: str = Field(default="", max_length=128)
    bank_name: str = Field(default="", max_length=128)
    bank_branch_id: str = Field(default="", max_length=128)
    account_number: str = Field(default="", max_length=32)
    settlement_id: str = Field(default="", max_length=32)
    qualification_type: str = Field(default="", max_length=128)
    settlement_rule_confirmed: bool = False
    addition_message: str = Field(default="", max_length=512)


class CreateApplyment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: str = Field(min_length=1, max_length=36)
    connection_id: str = Field(min_length=1, max_length=36)


class SaveApplyment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    fields: IndividualFields


class ApplymentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class SubmitApplyment(ApplymentAction):
    merchant_authorized: Literal[True]
    confirm_real_submission: Literal[True]


class AttachmentResponse(BaseModel):
    kind: str
    size_bytes: int


class ApplymentResponse(BaseModel):
    id: str
    store_id: str
    connection_id: str
    business_code: str
    sp_mchid: str
    platform_app_id: str
    state: str
    applyment_id: str | None
    sub_mchid: str | None
    last_error_code: str | None
    last_request_id: str | None
    version: int
    updated_at: datetime
    editable: bool
    fields: IndividualFields | None = None
    attachments: list[AttachmentResponse] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    audit_details: list[str] = Field(default_factory=list)
    sign_url: str | None = None


class ApplymentCapabilities(BaseModel):
    real_submission_enabled: bool
    subject_type: str = "个体工商户"
    administrator_type: str = "经营者本人"
    identity_document_type: str = "中国大陆居民身份证"
    max_image_bytes: int = MAX_IMAGE_BYTES
