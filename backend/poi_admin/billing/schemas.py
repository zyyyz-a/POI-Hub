"""API contracts for platform SaaS billing."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)
    price: int = Field(ge=0, le=100_000_000)
    billing_period: Literal["monthly", "yearly"] = "monthly"
    period_days: int = Field(default=30, ge=1, le=3660)


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    price: int | None = Field(default=None, ge=0, le=100_000_000)
    period_days: int | None = Field(default=None, ge=1, le=3660)
    status: Literal["active", "archived"] | None = None
    version: int = Field(ge=1)


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    description: str
    price: int
    billing_period: str
    period_days: int
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class SubscriptionCreate(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=36)
    plan_id: str = Field(min_length=1, max_length=36)
    period_start: datetime | None = None
    grace_days: int = Field(default=7, ge=0, le=365)


class SubscriptionUpdate(BaseModel):
    status: Literal["active", "past_due", "suspended", "cancelled"] | None = None
    grace_until: datetime | None = None
    version: int = Field(ge=1)


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    plan_id: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    grace_until: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class UsageEventCreate(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=36)
    event_type: str = Field(min_length=1, max_length=80)
    quantity: int = Field(default=1, ge=1, le=1_000_000)
    unit_amount: int = Field(default=0, ge=0, le=100_000_000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    occurred_at: datetime | None = None


class UsageEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    subscription_id: str | None
    event_type: str
    quantity: int
    unit_amount: int
    amount: int
    occurred_at: datetime
    created_at: datetime


class InvoiceGenerate(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=36)
    period_start: datetime
    period_end: datetime
    due_at: datetime | None = None
    description: str = Field(default="SaaS 服务费", max_length=200)
    amount: int | None = Field(default=None, ge=0, le=100_000_000)


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    subscription_id: str | None
    invoice_no: str
    period_start: datetime | None
    period_end: datetime | None
    amount: int
    paid_amount: int
    status: str
    issued_at: datetime
    due_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class InvoiceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    invoice_id: str
    description: str
    quantity: int
    unit_amount: int
    amount: int
    source_type: str
    source_id: str | None


class PaymentCreate(BaseModel):
    amount: int = Field(gt=0, le=100_000_000)
    method: Literal["bank_transfer", "payment_code", "cash", "other"] = "bank_transfer"
    reference: str | None = Field(default=None, max_length=200)
    received_at: datetime | None = None


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    invoice_id: str
    amount: int
    method: str
    reference: str | None
    received_at: datetime
    created_at: datetime


class AdjustmentCreate(BaseModel):
    kind: Literal["discount", "refund", "writeoff", "surcharge"]
    amount: int = Field(le=100_000_000, ge=-100_000_000)
    reason: str = Field(min_length=1, max_length=500)


class AdjustmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    invoice_id: str | None
    kind: str
    amount: int
    reason: str
    voided: bool
    created_at: datetime


class BillingSummaryResponse(BaseModel):
    subscription: SubscriptionResponse | None
    plan: PlanResponse | None
    outstanding_amount: int
    blocked: bool
    blockers: list[str]


__all__ = [
    "AdjustmentCreate",
    "AdjustmentResponse",
    "BillingSummaryResponse",
    "InvoiceGenerate",
    "InvoiceItemResponse",
    "InvoiceResponse",
    "PaymentCreate",
    "PaymentResponse",
    "PlanCreate",
    "PlanResponse",
    "PlanUpdate",
    "SubscriptionCreate",
    "SubscriptionResponse",
    "SubscriptionUpdate",
    "UsageEventCreate",
    "UsageEventResponse",
]
