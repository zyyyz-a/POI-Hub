"""Deterministic in-memory gateways for local demos and contract tests."""

from __future__ import annotations

import hashlib
from typing import Any

from .ports import (
    GatewayTerminalError,
    GatewayTransientError,
    OrderResult,
    PoiResult,
    ProductResult,
    VoucherResult,
)


def _short(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


class _ScenarioMixin:
    def __init__(self, tenant_id: str, *, scenario: str = "healthy") -> None:
        self.tenant_id = tenant_id
        self.scenario = scenario

    def _check(self, operation: str) -> None:
        if self.scenario in {"rate_limit", "timeout", "server_error"}:
            code = {
                "rate_limit": "rate_limited",
                "timeout": "timeout",
                "server_error": "upstream_5xx",
            }[self.scenario]
            message = {
                "rate_limit": "mock rate limit",
                "timeout": "mock timeout",
                "server_error": "mock server error",
            }[self.scenario]
            raise GatewayTransientError(message, code=code)
        if self.scenario in {"invalid", "permission_denied"}:
            code = (
                "permission_denied" if self.scenario == "permission_denied" else "invalid_request"
            )
            raise GatewayTerminalError("mock terminal error", code=code)


class MockLocalLifeGateway(_ScenarioMixin):
    def __init__(self, tenant_id: str, *, scenario: str = "healthy") -> None:
        super().__init__(tenant_id, scenario=scenario)
        self._products: dict[str, ProductResult] = {}
        self._stocks: dict[tuple[str, str], int] = {}
        self._vouchers: dict[str, VoucherResult] = {
            f"mock-voucher-{_short(tenant_id)}-1": VoucherResult(
                external_id=f"mock-voucher-{_short(tenant_id)}-1",
                state="available",
                product_id="mock-product-seeded",
            ),
            f"mock-voucher-{_short(tenant_id)}-2": VoucherResult(
                external_id=f"mock-voucher-{_short(tenant_id)}-2",
                state="available",
                product_id="mock-product-seeded",
            ),
        }

    async def create_product(self, payload: dict[str, Any]) -> ProductResult:
        self._check("create_product")
        external_id = "mock-product-" + _short(
            self.tenant_id + str(payload.get("merchant_product_id", len(self._products) + 1))
        )
        result = ProductResult(
            external_id, str(payload.get("name", "Mock 团购商品")), raw=dict(payload)
        )
        self._products[external_id] = result
        return result

    async def update_product(self, external_id: str, payload: dict[str, Any]) -> ProductResult:
        self._check("update_product")
        current = await self.get_product(external_id)
        result = ProductResult(
            external_id,
            str(payload.get("name", current.name)),
            str(payload.get("status", current.status)),
            {**current.raw, **payload},
        )
        self._products[external_id] = result
        return result

    async def get_product(self, external_id: str) -> ProductResult:
        self._check("get_product")
        if external_id not in self._products:
            return ProductResult(external_id, "Mock 商品", raw={"external_id": external_id})
        return self._products[external_id]

    async def audit_free_update_product(
        self, external_id: str, payload: dict[str, Any]
    ) -> ProductResult:
        return await self.update_product(external_id, payload)

    async def list_products(
        self, cursor: str | None = None
    ) -> tuple[list[ProductResult], str | None]:
        self._check("list_products")
        return list(self._products.values()), None

    async def delete_product(self, external_id: str) -> None:
        self._check("delete_product")
        self._products.pop(external_id, None)

    async def _set_product_status(self, external_id: str, status: str) -> ProductResult:
        current = await self.get_product(external_id)
        result = ProductResult(external_id, current.name, status, current.raw)
        self._products[external_id] = result
        return result

    async def cancel_product_audit(self, external_id: str) -> ProductResult:
        self._check("cancel_product_audit")
        return await self._set_product_status(external_id, "draft")

    async def list_product(self, external_id: str) -> ProductResult:
        self._check("list_product")
        return await self._set_product_status(external_id, "listed")

    async def delist_product(self, external_id: str) -> ProductResult:
        self._check("delist_product")
        return await self._set_product_status(external_id, "delisted")

    async def update_stock(self, external_id: str, sku_id: str, stock: int) -> dict[str, Any]:
        self._check("update_stock")
        if stock < 0:
            raise GatewayTerminalError("stock cannot be negative", code="invalid_stock")
        self._stocks[(external_id, sku_id)] = stock
        return {"product_id": external_id, "sku_id": sku_id, "stock": stock}

    async def upload_voucher_codes(
        self, external_id: str, sku_id: str, codes: list[str]
    ) -> dict[str, Any]:
        self._check("upload_voucher_codes")
        if len(codes) != len(set(codes)):
            raise GatewayTerminalError("voucher codes must be unique", code="duplicate_code")
        return {"product_id": external_id, "sku_id": sku_id, "accepted_count": len(codes)}

    async def get_order(self, external_id: str) -> OrderResult:
        self._check("get_order")
        return OrderResult(external_id, "paid", 9900, {"tenant_id": self.tenant_id})

    async def list_vouchers(self, order_id: str | None = None) -> list[VoucherResult]:
        self._check("list_vouchers")
        return list(self._vouchers.values())

    async def get_voucher(self, external_id: str) -> VoucherResult:
        self._check("get_voucher")
        return self._vouchers.get(external_id, VoucherResult(external_id, "available"))

    async def consume_voucher(self, external_id: str, *, out_store_id: str) -> VoucherResult:
        self._check("consume_voucher")
        current = await self.get_voucher(external_id)
        if current.state == "consumed":
            return current
        if current.state != "available":
            raise GatewayTerminalError("voucher is not available", code="voucher_state")
        result = VoucherResult(
            external_id, "consumed", current.product_id, out_store_id, current.raw
        )
        self._vouchers[external_id] = result
        return result

    async def revoke_consumption(
        self, external_id: str, *, out_store_id: str | None = None
    ) -> VoucherResult:
        self._check("revoke_consumption")
        current = await self.get_voucher(external_id)
        if current.state != "consumed":
            raise GatewayTerminalError("voucher is not consumed", code="voucher_state")
        result = VoucherResult(
            external_id, "available", current.product_id, out_store_id, current.raw
        )
        self._vouchers[external_id] = result
        return result

    async def get_after_sale(self, external_id: str) -> dict[str, Any]:
        self._check("get_after_sale")
        return {"external_id": external_id, "status": "none"}

    async def list_funds(
        self, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._check("list_funds")
        return ([{"id": "mock-fund-1", "amount": 9900, "currency": "CNY"}], None)

    async def list_bills(
        self, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._check("list_bills")
        return ([{"id": "mock-bill-1", "amount": 9900, "currency": "CNY"}], None)


class MockServicePoiGateway(_ScenarioMixin):
    def __init__(self, tenant_id: str, *, scenario: str = "healthy") -> None:
        super().__init__(tenant_id, scenario=scenario)
        suffix = _short(tenant_id)
        self._pois: dict[str, PoiResult] = {
            f"mock-poi-{suffix}-1": PoiResult(
                f"mock-poi-{suffix}-1", "西湖门店", "杭州市西湖区孤山路 1 号", 30.25, 120.16
            ),
            f"mock-poi-{suffix}-2": PoiResult(
                f"mock-poi-{suffix}-2", "湖滨门店", "杭州市上城区湖滨路 2 号", 30.25, 120.17
            ),
        }

    async def list_pois(self, cursor: str | None = None) -> list[PoiResult]:
        self._check("list_pois")
        return list(self._pois.values())

    async def get_poi(self, poi_id: str) -> PoiResult:
        self._check("get_poi")
        return self._pois.get(poi_id, PoiResult(poi_id, "Mock 门店", "未知地址"))

    async def search_pois(self, keyword: str) -> list[PoiResult]:
        self._check("search_pois")
        key = keyword.casefold()
        return [
            item
            for item in self._pois.values()
            if key in item.name.casefold() or key in item.address.casefold()
        ]

    async def create_poi(self, payload: dict[str, Any]) -> PoiResult:
        self._check("create_poi")
        poi_id = "mock-poi-" + _short(
            self.tenant_id + str(payload.get("name", len(self._pois) + 1))
        )
        result = PoiResult(
            poi_id,
            str(payload.get("name", "Mock 门店")),
            str(payload.get("address", "未知地址")),
            payload.get("latitude"),
            payload.get("longitude"),
            "pending",
            dict(payload),
        )
        self._pois[poi_id] = result
        return result

    async def update_poi(self, poi_id: str, payload: dict[str, Any]) -> PoiResult:
        self._check("update_poi")
        current = await self.get_poi(poi_id)
        result = PoiResult(
            poi_id,
            str(payload.get("name", current.name)),
            str(payload.get("address", current.address)),
            payload.get("latitude", current.latitude),
            payload.get("longitude", current.longitude),
            current.status,
            {**current.raw, **payload},
        )
        self._pois[poi_id] = result
        return result

    async def delete_poi(self, poi_id: str) -> None:
        self._check("delete_poi")
        self._pois.pop(poi_id, None)

    async def get_audit_status(self, poi_id: str) -> str:
        self._check("get_audit_status")
        return (await self.get_poi(poi_id)).status


__all__ = ["MockLocalLifeGateway", "MockServicePoiGateway"]
