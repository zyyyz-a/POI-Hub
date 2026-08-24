"""Deterministic in-memory gateways for local demos and contract tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .ports import (
    GatewayTerminalError,
    GatewayTransientError,
    OrderResult,
    PoiResult,
    ProductResult,
    SkuResult,
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


@dataclass(slots=True)
class _LocalLifeState:
    products: dict[str, ProductResult] = field(default_factory=dict)
    stocks: dict[tuple[str, str], int] = field(default_factory=dict)
    vouchers: dict[str, VoucherResult] = field(default_factory=dict)


class MockLocalLifeGateway(_ScenarioMixin):
    _states: ClassVar[dict[str, _LocalLifeState]] = {}

    def __init__(self, tenant_id: str, *, scenario: str = "healthy") -> None:
        super().__init__(tenant_id, scenario=scenario)
        state = self._states.setdefault(tenant_id, _LocalLifeState())
        if not state.vouchers:
            state.vouchers = {
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
        self._products = state.products
        self._stocks = state.stocks
        self._vouchers = state.vouchers

    async def create_product(self, payload: dict[str, Any]) -> ProductResult:
        self._check("create_product")
        external_id = "mock-product-" + _short(
            self.tenant_id + str(payload.get("merchant_product_id", len(self._products) + 1))
        )
        existing = self._products.get(external_id)
        if existing is not None:
            return existing
        raw_skus = payload.get("skus")
        sku_payloads = raw_skus if isinstance(raw_skus, list) and raw_skus else [{}]
        skus: list[SkuResult] = []
        for index, sku_payload in enumerate(sku_payloads):
            item = sku_payload if isinstance(sku_payload, dict) else {}
            merchant_sku_id = str(item.get("merchant_sku_id") or f"sku-{index + 1}")
            external_sku_id = (
                "sku-1"
                if not isinstance(raw_skus, list) or not raw_skus
                else "mock-sku-" + _short(external_id + merchant_sku_id)
            )
            skus.append(SkuResult(external_sku_id, merchant_sku_id))
        result = ProductResult(
            external_id,
            str(payload.get("name", "Mock 团购商品")),
            "under_review",
            dict(payload),
            tuple(skus),
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
            current.skus,
        )
        self._products[external_id] = result
        return result

    async def get_product(self, external_id: str) -> ProductResult:
        self._check("get_product")
        if external_id not in self._products:
            raise GatewayTerminalError("product was not found", code="product_not_found")
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
        product = await self.get_product(external_id)
        self._products.pop(external_id, None)
        for sku in product.skus:
            self._stocks.pop((external_id, sku.external_id), None)

    async def _set_product_status(self, external_id: str, status: str) -> ProductResult:
        current = await self.get_product(external_id)
        result = ProductResult(external_id, current.name, status, current.raw, current.skus)
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
        product = await self.get_product(external_id)
        if sku_id not in {sku.external_id for sku in product.skus}:
            raise GatewayTerminalError("SKU was not found", code="sku_not_found")
        self._stocks[(external_id, sku_id)] = stock
        return {"product_id": external_id, "sku_id": sku_id, "stock": stock}

    async def upload_voucher_codes(
        self, external_id: str, sku_id: str, codes: list[str]
    ) -> dict[str, Any]:
        self._check("upload_voucher_codes")
        product = await self.get_product(external_id)
        if sku_id not in {sku.external_id for sku in product.skus}:
            raise GatewayTerminalError("SKU was not found", code="sku_not_found")
        if len(codes) != len(set(codes)):
            raise GatewayTerminalError("voucher codes must be unique", code="duplicate_code")
        return {"product_id": external_id, "sku_id": sku_id, "accepted_count": len(codes)}

    async def get_order(self, external_id: str) -> OrderResult:
        self._check("get_order")
        return OrderResult(external_id, "paid", 9900, {"tenant_id": self.tenant_id})

    async def list_vouchers(
        self,
        openid: str,
        *,
        status: int | None = None,
        cursor: str | None = None,
    ) -> list[VoucherResult]:
        self._check("list_vouchers")
        del openid, cursor
        values = list(self._vouchers.values())
        if status is None:
            return values
        states = {1: "available", 2: "consumed", 3: "refunded", 4: "expired", 5: "reserved"}
        return [item for item in values if item.state == states.get(status)]

    async def get_voucher(self, external_id: str, *, sku_id: str) -> VoucherResult:
        self._check("get_voucher")
        del sku_id
        return self._vouchers.get(external_id, VoucherResult(external_id, "available"))

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
    ) -> VoucherResult:
        self._check("consume_voucher")
        del consume_request_no, consume_store_name, consume_channel, reserve_no
        current = await self.get_voucher(external_id, sku_id=sku_id)
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
        self,
        external_id: str,
        *,
        sku_id: str,
        revoke_request_no: str,
        consume_request_no: str | None = None,
    ) -> VoucherResult:
        self._check("revoke_consumption")
        del revoke_request_no, consume_request_no
        current = await self.get_voucher(external_id, sku_id=sku_id)
        if current.state != "consumed":
            raise GatewayTerminalError("voucher is not consumed", code="voucher_state")
        result = VoucherResult(
            external_id, "available", current.product_id, current.consume_store_id, current.raw
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
        self, product_id: str, bill_date: str, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._check("list_bills")
        del product_id, bill_date, cursor
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
