"""Typed gateway contracts for the two independent WeChat capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Capability(StrEnum):
    LOCAL_LIFE = "local_life"
    SERVICE_POI = "service_poi"


class ConnectionMode(StrEnum):
    MOCK = "mock"
    LIVE = "live"


class AuthorizationState(StrEnum):
    DISCONNECTED = "disconnected"
    AUTHORIZED = "authorized"
    ERROR = "error"


class GatewayError(Exception):
    """Safe error from a remote connector."""

    def __init__(
        self, message: str, *, code: str = "gateway_error", retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class GatewayTransientError(GatewayError):
    def __init__(self, message: str, *, code: str = "upstream_unavailable") -> None:
        super().__init__(message, code=code, retryable=True)


class GatewayTerminalError(GatewayError):
    def __init__(self, message: str, *, code: str = "invalid_request") -> None:
        super().__init__(message, code=code, retryable=False)


@dataclass(frozen=True, slots=True)
class SkuResult:
    external_id: str
    merchant_sku_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProductResult:
    external_id: str
    name: str
    status: str = "draft"
    raw: dict[str, Any] = field(default_factory=dict)
    skus: tuple[SkuResult, ...] = ()


@dataclass(frozen=True, slots=True)
class OrderResult:
    external_id: str
    status: str
    total_amount: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VoucherResult:
    external_id: str
    state: str
    product_id: str | None = None
    consume_store_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PoiResult:
    poi_id: str
    name: str
    address: str
    latitude: float | None = None
    longitude: float | None = None
    status: str = "approved"
    raw: dict[str, Any] = field(default_factory=dict)


class LocalLifeGateway(Protocol):
    async def create_product(self, payload: dict[str, Any]) -> ProductResult: ...

    async def update_product(self, external_id: str, payload: dict[str, Any]) -> ProductResult: ...

    async def audit_free_update_product(
        self, external_id: str, payload: dict[str, Any]
    ) -> ProductResult: ...

    async def get_product(self, external_id: str) -> ProductResult: ...

    async def list_products(
        self, cursor: str | None = None
    ) -> tuple[list[ProductResult], str | None]: ...

    async def delete_product(self, external_id: str) -> None: ...

    async def cancel_product_audit(self, external_id: str) -> ProductResult: ...

    async def list_product(self, external_id: str) -> ProductResult: ...

    async def delist_product(self, external_id: str) -> ProductResult: ...

    async def update_stock(self, external_id: str, sku_id: str, stock: int) -> dict[str, Any]: ...

    async def upload_voucher_codes(
        self, external_id: str, sku_id: str, codes: list[str]
    ) -> dict[str, Any]: ...

    async def get_order(self, external_id: str) -> OrderResult: ...

    async def list_vouchers(
        self,
        openid: str,
        *,
        status: int | None = None,
        cursor: str | None = None,
    ) -> list[VoucherResult]: ...

    async def get_voucher(self, external_id: str, *, sku_id: str) -> VoucherResult: ...

    async def consume_voucher(
        self,
        external_id: str,
        *,
        sku_id: str,
        consume_request_no: str,
        out_store_id: str,
        consume_store_name: str | None = None,
        consume_channel: int = 2,
        reserve_no: str | None = None,
    ) -> VoucherResult: ...

    async def revoke_consumption(
        self,
        external_id: str,
        *,
        sku_id: str,
        revoke_request_no: str,
        consume_request_no: str | None = None,
    ) -> VoucherResult: ...

    async def get_after_sale(self, external_id: str) -> dict[str, Any]: ...

    async def list_funds(
        self, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    async def list_bills(
        self, product_id: str, bill_date: str, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]: ...


class ServicePoiGateway(Protocol):
    async def list_pois(self, cursor: str | None = None) -> list[PoiResult]: ...

    async def get_poi(self, poi_id: str) -> PoiResult: ...

    async def search_pois(self, keyword: str) -> list[PoiResult]: ...

    async def create_poi(self, payload: dict[str, Any]) -> PoiResult: ...

    async def update_poi(self, poi_id: str, payload: dict[str, Any]) -> PoiResult: ...

    async def delete_poi(self, poi_id: str) -> None: ...

    async def get_audit_status(self, poi_id: str) -> str: ...


__all__ = [
    "AuthorizationState",
    "Capability",
    "ConnectionMode",
    "GatewayError",
    "GatewayTerminalError",
    "GatewayTransientError",
    "LocalLifeGateway",
    "OrderResult",
    "PoiResult",
    "ProductResult",
    "ServicePoiGateway",
    "SkuResult",
    "VoucherResult",
]
