"""Validated Local Life product and inventory API contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_admin.operations.models import OperationStatus

from .models import ProductStatus


class ProductAction(StrEnum):
    CANCEL_AUDIT = "cancel_audit"
    LIST = "list"
    DELIST = "delist"
    DELETE = "delete"


class SkuCreateRequest(BaseModel):
    merchant_sku_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=160)
    sale_price: int = Field(gt=0, le=2_000_000_000)
    market_price: int = Field(gt=0, le=2_000_000_000)
    stock: int = Field(ge=0, le=2_000_000_000)

    @field_validator("merchant_sku_id", "name")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @model_validator(mode="after")
    def validate_prices(self) -> Self:
        if self.sale_price > self.market_price:
            raise ValueError("sale_price cannot exceed market_price")
        return self


class ProductCreateRequest(BaseModel):
    connection_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(min_length=1, max_length=255)
    merchant_product_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=3, max_length=60)
    product_type: Literal[
        "group_buying", "cash_voucher", "exchange_voucher", "multi_use_card"
    ] = "cash_voucher"
    category: str = Field(min_length=1, max_length=160)
    brand: str = Field(min_length=1, max_length=160)
    head_images: list[str] = Field(min_length=1, max_length=9)
    available_store_desc: str | None = Field(default=None, max_length=1000)
    verification_settings: dict[str, Any] = Field(default_factory=dict)
    code_source: Literal["wechat", "merchant"] = "wechat"
    rules: dict[str, Any] = Field(min_length=1)
    skus: list[SkuCreateRequest] = Field(min_length=1, max_length=50)

    @field_validator("connection_id", "idempotency_key", "merchant_product_id", "name")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @field_validator("category", "brand", "available_store_desc")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("head_images")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped.startswith(("https://", "http://")):
                raise ValueError("head image must be an HTTP URL")
            normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def validate_unique_skus(self) -> Self:
        merchant_ids = [sku.merchant_sku_id for sku in self.skus]
        if len(merchant_ids) != len(set(merchant_ids)):
            raise ValueError("merchant_sku_id must be unique within a product")
        return self


class StockUpdateRequest(BaseModel):
    stock: int = Field(ge=0, le=2_000_000_000)
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("idempotency_key")
    @classmethod
    def strip_idempotency_key(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("idempotency_key cannot be blank")
        return stripped


class ProductUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=160)
    brand: str | None = Field(default=None, max_length=160)
    head_images: list[str] | None = None
    available_store_desc: str | None = Field(default=None, max_length=1000)
    verification_settings: dict[str, Any] | None = None
    code_source: Literal["wechat", "merchant"] | None = None
    rules: dict[str, Any] | None = None

    @field_validator("idempotency_key")
    @classmethod
    def strip_idempotency_key(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("idempotency_key cannot be blank")
        return stripped

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("name cannot be null")
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank")
        return stripped

    @field_validator("category", "brand", "available_store_desc")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("head_images")
    @classmethod
    def validate_images(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            raise ValueError("head_images cannot be null")
        if not 1 <= len(values) <= 9:
            raise ValueError("head_images must contain between 1 and 9 items")
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped.startswith(("https://", "http://")):
                raise ValueError("head image must be an HTTP URL")
            normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> Self:
        editable_fields = {
            "name",
            "category",
            "brand",
            "head_images",
            "available_store_desc",
            "verification_settings",
            "code_source",
            "rules",
        }
        if not self.model_fields_set.intersection(editable_fields):
            raise ValueError("at least one product field must be changed")
        if "verification_settings" in self.model_fields_set and self.verification_settings is None:
            raise ValueError("verification_settings cannot be null")
        if "rules" in self.model_fields_set and self.rules is None:
            raise ValueError("rules cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(
            exclude={"version", "idempotency_key"},
            exclude_unset=True,
        )


class ProductActionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("idempotency_key")
    @classmethod
    def strip_idempotency_key(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("idempotency_key cannot be blank")
        return stripped


class SkuResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    product_id: str
    external_sku_id: str | None
    merchant_sku_id: str
    name: str
    sale_price: int
    market_price: int
    stock: int
    desired_stock: int
    sold_count: int
    version: int
    last_stock_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str
    external_product_id: str | None
    merchant_product_id: str
    product_type: str
    name: str
    category: str | None
    brand: str | None
    head_images: list[str]
    available_store_desc: str | None
    verification_settings: dict[str, Any]
    code_source: str
    rules: dict[str, Any]
    remote_status: ProductStatus
    desired_state: ProductStatus
    version: int
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
    skus: list[SkuResponse]


class ProductAcceptedResponse(BaseModel):
    operation_id: str
    status: OperationStatus
    product: ProductResponse


class StockAcceptedResponse(BaseModel):
    operation_id: str
    status: OperationStatus
    sku: SkuResponse


class OrderSyncRequest(BaseModel):
    connection_id: str = Field(min_length=1, max_length=36)
    external_order_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("connection_id", "external_order_id", "idempotency_key")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class ConsumeVoucherRequest(BaseModel):
    store_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    reserve_no: str | None = Field(default=None, max_length=128)

    @field_validator("store_id")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def strip_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("reserve_no")
    @classmethod
    def strip_reserve_no(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class RevokeVoucherRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    store_id: str | None = Field(default=None, max_length=160)

    @field_validator("idempotency_key")
    @classmethod
    def strip_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("store_id")
    @classmethod
    def strip_store(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AfterSaleSyncRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=36)
    external_after_sale_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("order_id", "external_after_sale_id", "idempotency_key")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class AccountingSyncRequest(BaseModel):
    connection_id: str = Field(min_length=1, max_length=36)
    product_id: str = Field(min_length=1, max_length=160)
    bill_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("connection_id", "product_id", "bill_date", "idempotency_key")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class OperationResponse(BaseModel):
    id: str
    status: OperationStatus
    command_type: str


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str
    external_order_id: str
    status: str
    total_amount: int
    paid_amount: int
    currency: str
    customer_reference_masked: str | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OrderAcceptedResponse(BaseModel):
    operation: OperationResponse
    order: OrderResponse


class VoucherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str
    order_id: str | None
    external_voucher_id: str
    external_product_id: str | None
    external_sku_id: str | None
    code_masked: str
    state: str
    valid_from: datetime | None
    valid_until: datetime | None
    consume_store_id: str | None
    consumed_at: datetime | None
    revoked_at: datetime | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VoucherAcceptedResponse(BaseModel):
    operation: OperationResponse
    voucher: VoucherResponse


class AfterSaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str
    order_id: str | None
    external_after_sale_id: str
    after_sale_type: str | None
    status: str
    refund_amount: int
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AccountingEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str
    external_id: str
    entry_type: str | None
    amount: int
    currency: str
    occurred_at: datetime | None


class ReconciliationSummary(BaseModel):
    fund_count: int
    bill_count: int
    fund_total: int
    bill_total: int
    difference: int
    difference_count: int
    differences: list[dict[str, Any]]
    linked_order_count: int = 0
    unmatched_fund_count: int = 0
    unmatched_bill_count: int = 0
    funds: list[dict[str, Any]] = Field(default_factory=list)
    bills: list[dict[str, Any]] = Field(default_factory=list)


class AccountingAcceptedResponse(BaseModel):
    operation: OperationResponse
    summary: ReconciliationSummary


__all__ = [
    "ProductAcceptedResponse",
    "ProductAction",
    "ProductActionRequest",
    "ProductCreateRequest",
    "ProductResponse",
    "ProductUpdateRequest",
    "AccountingAcceptedResponse",
    "AccountingEntryResponse",
    "AccountingSyncRequest",
    "AfterSaleResponse",
    "AfterSaleSyncRequest",
    "ConsumeVoucherRequest",
    "OrderAcceptedResponse",
    "OrderResponse",
    "OrderSyncRequest",
    "OperationResponse",
    "ReconciliationSummary",
    "RevokeVoucherRequest",
    "SkuCreateRequest",
    "SkuResponse",
    "StockAcceptedResponse",
    "StockUpdateRequest",
    "VoucherAcceptedResponse",
    "VoucherResponse",
]
