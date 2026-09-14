"""API contracts for the merchant-owned mini-program commerce flow."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DirectProductCreate(BaseModel):
    mini_program_id: str
    store_id: str
    merchant_product_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    cover_image: str | None = Field(default=None, max_length=500)
    sale_price: int = Field(gt=0, le=100_000_000)
    market_price: int = Field(gt=0, le=100_000_000)
    stock: int = Field(ge=0, le=10_000_000)
    appointment_required: bool = True
    service_minutes: int = Field(default=60, ge=5, le=1440)


class DirectProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    cover_image: str | None = Field(default=None, max_length=500)
    sale_price: int | None = Field(default=None, gt=0, le=100_000_000)
    market_price: int | None = Field(default=None, gt=0, le=100_000_000)
    stock: int | None = Field(default=None, ge=0, le=10_000_000)
    appointment_required: bool | None = None
    service_minutes: int | None = Field(default=None, ge=5, le=1440)
    status: Literal["draft", "listed", "delisted"] | None = None
    version: int = Field(ge=1)


class DirectProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    mini_program_id: str
    store_id: str
    merchant_product_id: str
    name: str
    description: str
    cover_image: str | None
    sale_price: int
    market_price: int
    stock: int
    sold_count: int
    appointment_required: bool
    service_minutes: int
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class ConsumerLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class ConsumerSessionResponse(BaseModel):
    access_token: str
    expires_at: datetime


class DirectOrderCreate(BaseModel):
    product_id: str
    quantity: int = 1
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("quantity")
    @classmethod
    def single_use_only(cls, value: int) -> int:
        if value != 1:
            raise ValueError("每单限购 1 份，请分单购买")
        return value


class DirectOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    mini_program_id: str
    store_id: str
    product_id: str
    order_no: str
    product_name: str
    quantity: int
    unit_amount: int
    total_amount: int
    paid_amount: int
    status: str
    expires_at: datetime
    paid_at: datetime | None
    created_at: datetime


class PaymentRequest(BaseModel):
    description: str | None = Field(default=None, max_length=127)


class PaymentResponse(BaseModel):
    order: DirectOrderResponse
    payment_parameters: dict[str, str]
    mock_voucher_code: str | None = None


class AppointmentCreate(BaseModel):
    starts_at: datetime
    contact_name: str = Field(min_length=1, max_length=80)
    contact_phone: str = Field(min_length=7, max_length=32)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("contact_phone")
    @classmethod
    def phone_is_plain_number(cls, value: str) -> str:
        normalized = value.replace(" ", "").replace("-", "")
        if not normalized.lstrip("+").isdigit():
            raise ValueError("联系电话格式不正确")
        return normalized


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    order_id: str
    store_id: str
    starts_at: datetime
    contact_name: str
    contact_phone_masked: str
    note: str | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class VoucherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    order_id: str
    code_masked: str
    state: str
    valid_until: datetime
    consumed_at: datetime | None
    consume_store_id: str | None
    version: int
    created_at: datetime


class VoucherConsumeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=64)
    store_id: str


class VoucherRevokeRequest(BaseModel):
    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class PaymentProfileCreate(BaseModel):
    store_id: str = Field(min_length=1, max_length=36)
    connection_id: str | None = Field(default=None, max_length=36)
    mode: Literal["ordinary", "partner"] = "ordinary"
    mchid: str | None = Field(default=None, max_length=128)
    sub_mchid: str | None = Field(default=None, max_length=128)
    sp_mchid: str | None = Field(default=None, max_length=128)
    verified: bool = False
    status: Literal["draft", "active", "disabled"] = "draft"


class PaymentProfileUpdate(BaseModel):
    connection_id: str | None = Field(default=None, max_length=36)
    mode: Literal["ordinary", "partner"] | None = None
    mchid: str | None = Field(default=None, max_length=128)
    sub_mchid: str | None = Field(default=None, max_length=128)
    sp_mchid: str | None = Field(default=None, max_length=128)
    verified: bool | None = None
    status: Literal["draft", "active", "disabled"] | None = None
    version: int = Field(ge=1)


class PaymentProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    store_id: str
    connection_id: str | None
    mode: str
    mchid: str | None
    sub_mchid: str | None
    sp_mchid: str | None
    verified: bool
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class StoreEntryResponse(BaseModel):
    store_code: str
    store_name: str
    address: str
    city: str | None
    district: str | None
    contact_phone_masked: str | None
    latitude: float | None
    longitude: float | None
    tradable: bool
    blockers: list[str]


__all__ = [
    "AppointmentCreate",
    "AppointmentResponse",
    "ConsumerLoginRequest",
    "ConsumerSessionResponse",
    "DirectOrderCreate",
    "DirectOrderResponse",
    "DirectProductCreate",
    "DirectProductResponse",
    "DirectProductUpdate",
    "PaymentProfileCreate",
    "PaymentProfileResponse",
    "PaymentProfileUpdate",
    "PaymentRequest",
    "PaymentResponse",
    "StoreEntryResponse",
    "VoucherConsumeRequest",
    "VoucherResponse",
    "VoucherRevokeRequest",
]
