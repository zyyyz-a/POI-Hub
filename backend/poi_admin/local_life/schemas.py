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
    name: str = Field(min_length=1, max_length=200)
    product_type: Literal["group_buying"] = "group_buying"
    category: str | None = Field(default=None, max_length=160)
    brand: str | None = Field(default=None, max_length=160)
    head_images: list[str] = Field(min_length=1, max_length=9)
    available_store_desc: str | None = Field(default=None, max_length=1000)
    verification_settings: dict[str, Any] = Field(default_factory=dict)
    code_source: Literal["wechat", "merchant"] = "wechat"
    rules: dict[str, Any] = Field(default_factory=dict)
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


__all__ = [
    "ProductAcceptedResponse",
    "ProductAction",
    "ProductActionRequest",
    "ProductCreateRequest",
    "ProductResponse",
    "SkuCreateRequest",
    "SkuResponse",
    "StockAcceptedResponse",
    "StockUpdateRequest",
]
