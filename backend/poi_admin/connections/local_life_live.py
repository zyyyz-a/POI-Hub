"""Live adapter for the documented WeChat Local Life APIs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .ports import (
    LocalLifeGateway,
    OrderResult,
    ProductResult,
    SkuResult,
    VoucherResult,
)
from .tokens import AccessTokenProvider
from .wechat_http import WeChatHttpClient


def _value(data: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return default


def _status(value: Any, *, default: str = "draft") -> str:
    if isinstance(value, str):
        return value
    statuses = {
        0: "draft",
        1: "under_review",
        2: "approved",
        3: "listed",
        5: "listed",
        11: "delisted",
        13: "delisted",
        14: "delisted",
        15: "delisted",
        20: "delisted",
    }
    try:
        return statuses.get(int(value), default)
    except (TypeError, ValueError):
        return default


def _product(data: Mapping[str, Any]) -> ProductResult:
    raw = dict(data)
    product_id = str(_value(data, "product_id", "id", "external_product_id", default=""))
    skus_raw = _value(data, "skus", "sku_list", default=[])
    skus = tuple(
        SkuResult(
            str(_value(sku, "sku_id", "id", default="")),
            str(_value(sku, "out_sku_id", "merchant_sku_id", default="")) or None,
        )
        for sku in skus_raw
        if isinstance(sku, Mapping)
    )
    return ProductResult(
        product_id,
        str(_value(data, "product_name", "name", default=product_id)),
        _status(_value(data, "online_status", "draft_status", "status")),
        raw,
        skus,
    )


def _voucher(data: Mapping[str, Any]) -> VoucherResult:
    raw = dict(data)
    states = {
        1: "available",
        2: "consumed",
        3: "refunded",
        4: "expired",
        5: "reserved",
    }
    raw_status = data.get("status")
    try:
        numeric_status = int(raw_status) if raw_status is not None else 0
        state = states.get(numeric_status, str(data.get("state", "available")))
    except (TypeError, ValueError):
        state = str(data.get("state", "available"))
    return VoucherResult(
        str(_value(data, "code", "voucher_id", "id", default="")),
        state,
        str(_value(data, "product_id", default="")) or None,
        str(_value(data, "out_store_id", "consume_store_name", default="")) or None,
        raw,
    )


class LiveLocalLifeGateway(LocalLifeGateway):
    def __init__(
        self,
        token_provider: AccessTokenProvider,
        *,
        base_url: str = "https://api.weixin.qq.com",
        http_client: Any = None,
    ) -> None:
        self.http = WeChatHttpClient(token_provider, base_url=base_url, http_client=http_client)

    async def create_product(self, payload: dict[str, Any]) -> ProductResult:
        body = {
            "out_product_id": payload.get("merchant_product_id"),
            "product_type": payload.get("product_type", 1),
            "product_name": payload.get("name"),
            "category_id": payload.get("category_id", payload.get("category")),
            "brand_id": payload.get("brand_id", payload.get("brand")),
        "head_imgs": payload.get("head_images", []),
            "product_qua_infos": payload.get("product_qua_infos", []),
            "verify_page": payload.get("verify_page", payload.get("verification_settings", {})),
            "verify_at_store": payload.get("verify_at_store", 1),
            "code_source_type": payload.get("code_source_type", payload.get("code_source", 1)),
            "attr_kv_map": payload.get("attr_kv_map", payload.get("rules", {})),
            "skus": payload.get("skus", []),
        }
        response = await self.http.post_json("/channels/ec/product/locallife/add", body)
        data = response.get("data") if isinstance(response.get("data"), Mapping) else response
        if not isinstance(data, Mapping):
            data = {}
        return _product({**body, **data, "product_id": data.get("product_id", data.get("id", ""))})

    async def update_product(self, external_id: str, payload: dict[str, Any]) -> ProductResult:
        return await self._update("/channels/ec/product/locallife/update", external_id, payload)

    async def audit_free_update_product(
        self, external_id: str, payload: dict[str, Any]
    ) -> ProductResult:
        return await self._update("/channels/ec/product/locallife/auditfree", external_id, payload)

    async def _update(
        self, path: str, external_id: str, payload: Mapping[str, Any]
    ) -> ProductResult:
        body = {
            "product_id": external_id,
            "product_name": payload.get("name"),
            "out_product_id": payload.get("merchant_product_id"),
            "product_type": payload.get("product_type", 1),
            "category_id": payload.get("category_id", payload.get("category")),
            "brand_id": payload.get("brand_id", payload.get("brand")),
            "head_imgs": payload.get("head_images", []),
            "attr_kv_map": payload.get("attr_kv_map", payload.get("rules", {})),
            "skus": payload.get("skus", []),
        }
        response = await self.http.post_json(
            path, {key: value for key, value in body.items() if value is not None}
        )
        data = response.get("data") if isinstance(response.get("data"), Mapping) else response
        return _product(
            {**body, **(dict(data) if isinstance(data, Mapping) else {}), "product_id": external_id}
        )

    async def get_product(self, external_id: str) -> ProductResult:
        response = await self.http.post_json(
            "/channels/ec/product/locallife/get", {"product_id": external_id, "data_type": 3}
        )
        data = (
            response.get("online_data")
            or response.get("draft_data")
            or response.get("data")
            or response
        )
        return _product(
            {**(dict(data) if isinstance(data, Mapping) else {}), "product_id": external_id}
        )

    async def list_products(
        self, cursor: str | None = None
    ) -> tuple[list[ProductResult], str | None]:
        body: dict[str, Any] = {"status": 0, "page_size": 30}
        if cursor:
            body["next_key"] = cursor
        response = await self.http.post_json("/channels/ec/product/locallife/list/get", body)
        product_ids = response.get("product_ids")
        if not isinstance(product_ids, list):
            nested = response.get("data")
            product_ids = nested.get("products", []) if isinstance(nested, Mapping) else []
        products: list[ProductResult] = []
        for item in product_ids:
            if isinstance(item, Mapping):
                products.append(_product(item))
            else:
                products.append(await self.get_product(str(item)))
        next_cursor = response.get("next_key")
        if not isinstance(next_cursor, str):
            nested = response.get("data")
            next_cursor = nested.get("next_cursor") if isinstance(nested, Mapping) else None
        return products, next_cursor or None

    async def _action(self, path: str, external_id: str, status: str) -> ProductResult:
        await self.http.post_json(path, {"product_id": external_id})
        return ProductResult(external_id, external_id, status, {"product_id": external_id})

    async def delete_product(self, external_id: str) -> None:
        await self.http.post_json("/channels/ec/product/delete", {"product_id": external_id})

    async def cancel_product_audit(self, external_id: str) -> ProductResult:
        return await self._action("/channels/ec/product/audit/cancel", external_id, "draft")

    async def list_product(self, external_id: str) -> ProductResult:
        return await self._action("/channels/ec/product/listing", external_id, "listed")

    async def delist_product(self, external_id: str) -> ProductResult:
        return await self._action("/channels/ec/product/delisting", external_id, "delisted")

    async def update_stock(self, external_id: str, sku_id: str, stock: int) -> dict[str, Any]:
        response = await self.http.post_json(
            "/channels/ec/product/stock/update",
            {"product_id": external_id, "sku_id": sku_id, "diff_type": 3, "num": stock},
        )
        return {"product_id": external_id, "sku_id": sku_id, "stock": stock, **response}

    async def upload_voucher_codes(
        self, external_id: str, sku_id: str, codes: list[str]
    ) -> dict[str, Any]:
        response = await self.http.post_json(
            "/channels/ec/voucher/codes/upload",
            {"product_id": external_id, "sku_id": sku_id, "codes": codes[:200]},
        )
        return {
            "product_id": external_id,
            "sku_id": sku_id,
            "accepted_count": len(codes),
            **response,
        }

    async def get_order(self, external_id: str) -> OrderResult:
        response = await self.http.post_json("/channels/ec/order/get", {"order_id": external_id})
        data = response.get("order_info") or response.get("data") or response
        data = dict(data) if isinstance(data, Mapping) else {}
        return OrderResult(
            external_id,
            str(_value(data, "status", "order_status", default="unknown")),
            int(_value(data, "pay_amount", "total_amount", default=0) or 0),
            data,
        )

    async def list_vouchers(self, order_id: str | None = None) -> list[VoucherResult]:
        # The documented endpoint filters by openid/status, not order id. The
        # protocol keeps order_id for the mock gateway and local call sites.
        del order_id
        body: dict[str, Any] = {"page_size": 50, "page_ctx": ""}
        response = await self.http.post_json("/channels/ec/voucher/get_list", body)
        values = response.get("voucher_list", [])
        return [_voucher(item) for item in values if isinstance(item, Mapping)]

    async def get_voucher(self, external_id: str) -> VoucherResult:
        response = await self.http.post_json("/channels/ec/voucher/get", {"code": external_id})
        data = response.get("voucher") or response.get("data") or response
        return _voucher(data if isinstance(data, Mapping) else {"code": external_id})

    async def consume_voucher(self, external_id: str, *, out_store_id: str) -> VoucherResult:
        response = await self.http.post_json(
            "/channels/ec/voucher/consume",
            {
                "consume_request_no": external_id,
                "codes": [external_id],
                "out_store_id": out_store_id,
                "consume_channel": 1,
            },
        )
        data = (
            response.get("voucher")
            or response.get("data")
            or {"code": external_id, "status": 2, "out_store_id": out_store_id}
        )
        return _voucher(
            data
            if isinstance(data, Mapping)
            else {"code": external_id, "status": 2, "out_store_id": out_store_id}
        )

    async def revoke_consumption(
        self, external_id: str, *, out_store_id: str | None = None
    ) -> VoucherResult:
        item: dict[str, Any] = {"code": external_id}
        if out_store_id:
            item["out_store_id"] = out_store_id
        response = await self.http.post_json(
            "/channels/ec/voucher/revoke",
            {"revoke_request_no": external_id, "reovke_vouchers": [item]},
        )
        data = response.get("voucher") or response.get("data") or {"code": external_id, "status": 1}
        return _voucher(data if isinstance(data, Mapping) else {"code": external_id, "status": 1})

    async def get_after_sale(self, external_id: str) -> dict[str, Any]:
        response = await self.http.post_json(
            "/channels/ec/aftersale/getaftersaleorder", {"after_sale_order_id": external_id}
        )
        return dict(response.get("after_sale_order") or response.get("data") or response)

    async def list_funds(
        self, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        body: dict[str, Any] = {"page": 1, "page_size": 50}
        if cursor:
            body["next_key"] = cursor
        response = await self.http.post_json("/channels/ec/funds/getfundsflowlist", body)
        values = (
            response.get("funds") or response.get("flow_list") or response.get("flow_ids") or []
        )
        return [
            dict(item) if isinstance(item, Mapping) else {"id": str(item)} for item in values
        ], response.get("next_key") or None

    async def list_bills(
        self, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        body: dict[str, Any] = {"page_size": 50, "page_ctx": cursor or ""}
        response = await self.http.post_json("/channels/ec/voucher/get_bill_list", body)
        values = response.get("bill_list", [])
        return [dict(item) for item in values if isinstance(item, Mapping)], response.get(
            "page_ctx"
        ) or None


__all__ = ["LiveLocalLifeGateway"]
