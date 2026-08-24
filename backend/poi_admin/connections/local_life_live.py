"""Live adapter for the documented WeChat Local Life APIs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .ports import (
    GatewayTerminalError,
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


def _product_type(value: Any) -> int:
    mapping = {
        "group_buying": 1,
        "cash_voucher": 1,
        "exchange_voucher": 2,
        "multi_use": 3,
        "multi_use_card": 3,
    }
    if isinstance(value, str):
        value = mapping.get(value.casefold(), value)
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise GatewayTerminalError(
            "本地生活券类型无效", code="invalid_product_type"
        ) from error
    if result not in {1, 2, 3}:
        raise GatewayTerminalError("本地生活券类型无效", code="invalid_product_type")
    return result


def _code_source_type(value: Any) -> int:
    mapping = {"wechat": 1, "platform": 1, "merchant": 2}
    if isinstance(value, str):
        value = mapping.get(value.casefold(), value)
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise GatewayTerminalError("券码来源无效", code="invalid_code_source") from error
    if result not in {1, 2}:
        raise GatewayTerminalError("券码来源无效", code="invalid_code_source")
    return result


def _attributes(payload: Mapping[str, Any]) -> dict[str, str]:
    source = payload.get("attr_kv_map", payload.get("rules", {}))
    if not isinstance(source, Mapping):
        raise GatewayTerminalError("商品属性格式无效", code="invalid_product_attributes")
    result: dict[str, str] = {}
    for key, value in source.items():
        if isinstance(value, str):
            result[str(key)] = value
        else:
            result[str(key)] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    store_description = payload.get("available_store_desc")
    if isinstance(store_description, str) and store_description.strip():
        result["available_store_desc"] = json.dumps(
            store_description.strip(), ensure_ascii=False
        )
    if not result:
        raise GatewayTerminalError(
            "商品属性不能为空", code="product_attributes_required"
        )
    return result


def _skus(payload: Mapping[str, Any]) -> list[dict[str, int]]:
    source = payload.get("skus", [])
    if not isinstance(source, list) or not source:
        raise GatewayTerminalError("商品 SKU 不能为空", code="product_skus_required")
    result: list[dict[str, int]] = []
    for item in source:
        if not isinstance(item, Mapping):
            raise GatewayTerminalError("商品 SKU 格式无效", code="invalid_product_sku")
        try:
            sale_price = int(item["sale_price"])
        except (KeyError, TypeError, ValueError) as error:
            raise GatewayTerminalError(
                "商品 SKU 售价无效", code="invalid_product_sku"
            ) from error
        if sale_price <= 0:
            raise GatewayTerminalError("商品 SKU 售价无效", code="invalid_product_sku")
        result.append({"sale_price": sale_price})
    return result


def _required_identifier(payload: Mapping[str, Any], primary: str, fallback: str) -> str:
    value = payload.get(primary, payload.get(fallback))
    if not isinstance(value, (str, int)) or not str(value).strip():
        raise GatewayTerminalError(
            f"商品字段 {primary} 不能为空", code="product_required_field"
        )
    return str(value).strip()


def _first_voucher(response: Mapping[str, Any], fallback: Mapping[str, Any]) -> Mapping[str, Any]:
    values = response.get("voucher_list")
    if isinstance(values, list) and values and isinstance(values[0], Mapping):
        return values[0]
    direct = response.get("voucher") or response.get("data")
    return direct if isinstance(direct, Mapping) else fallback


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
        category_id = _required_identifier(payload, "category_id", "category")
        brand_id = _required_identifier(payload, "brand_id", "brand")
        body = {
            "out_product_id": payload.get("merchant_product_id"),
            "product_type": _product_type(payload.get("product_type", 1)),
            "product_name": payload.get("name"),
            "category_id": category_id,
            "brand_id": brand_id,
            "head_imgs": payload.get("head_images", []),
            "verify_at_store": payload.get("verify_at_store", 1),
            "code_source_type": _code_source_type(
                payload.get("code_source_type", payload.get("code_source", 1))
            ),
            "attr_kv_map": _attributes(payload),
            "skus": _skus(payload),
        }
        qualifications = payload.get("product_qua_infos")
        if isinstance(qualifications, list) and qualifications:
            body["product_qua_infos"] = qualifications
        verify_page = payload.get("verify_page", payload.get("verification_settings"))
        if (
            isinstance(verify_page, Mapping)
            and verify_page.get("appid")
            and verify_page.get("path")
        ):
            body["verify_page"] = dict(verify_page)
        response = await self.http.post_json("/channels/ec/product/locallife/add", body)
        data = response.get("data") if isinstance(response.get("data"), Mapping) else response
        if not isinstance(data, Mapping):
            data = {}
        remote = dict(data)
        sku_ids = remote.get("sku_ids")
        if isinstance(sku_ids, list):
            remote["skus"] = [{"sku_id": str(sku_id)} for sku_id in sku_ids]
        return _product(
            {
                **body,
                **remote,
                "product_id": remote.get("product_id", remote.get("id", "")),
            }
        )

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
            "product_type": _product_type(payload.get("product_type", 1)),
            "category_id": payload.get("category_id", payload.get("category")),
            "brand_id": payload.get("brand_id", payload.get("brand")),
            "head_imgs": payload.get("head_images", []),
            "attr_kv_map": _attributes(payload),
            "skus": _skus(payload),
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
            accepted_error_codes=frozenset({10001}),
        )
        return {
            "product_id": external_id,
            "sku_id": sku_id,
            "accepted_count": int(response.get("success_count", len(codes)) or 0),
            "failed_count": int(response.get("fail_count", 0) or 0),
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

    async def list_vouchers(
        self,
        openid: str,
        *,
        status: int | None = None,
        cursor: str | None = None,
    ) -> list[VoucherResult]:
        if not openid.strip():
            raise GatewayTerminalError("openid 不能为空", code="openid_required")
        body: dict[str, Any] = {
            "openid": openid,
            "page_size": 50,
            "page_ctx": cursor or "",
        }
        if status is not None:
            body["status"] = status
        response = await self.http.post_json("/channels/ec/voucher/get_list", body)
        values = response.get("voucher_list", [])
        return [_voucher(item) for item in values if isinstance(item, Mapping)]

    async def get_voucher(self, external_id: str, *, sku_id: str) -> VoucherResult:
        response = await self.http.post_json(
            "/channels/ec/voucher/get", {"code": external_id, "sku_id": sku_id}
        )
        data = response.get("voucher") or response.get("data") or response
        return _voucher(data if isinstance(data, Mapping) else {"code": external_id})

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
        body: dict[str, Any] = {
            "consume_request_no": consume_request_no,
            "codes": [external_id],
            "sku_id": sku_id,
            "out_store_id": out_store_id,
            "consume_channel": consume_channel,
        }
        if consume_store_name:
            body["consume_store_name"] = consume_store_name
        if reserve_no:
            body["reserve_no"] = reserve_no
        response = await self.http.post_json(
            "/channels/ec/voucher/consume",
            body,
        )
        data = _first_voucher(
            response,
            {
                "code": external_id,
                "sku_id": sku_id,
                "status": 2,
                "out_store_id": out_store_id,
                "consume_store_name": consume_store_name,
            },
        )
        return _voucher(
            data
            if isinstance(data, Mapping)
            else {"code": external_id, "status": 2, "out_store_id": out_store_id}
        )

    async def revoke_consumption(
        self,
        external_id: str,
        *,
        sku_id: str,
        revoke_request_no: str,
        consume_request_no: str | None = None,
    ) -> VoucherResult:
        body: dict[str, Any] = {
            "revoke_request_no": revoke_request_no,
            "reovke_vouchers": [{"code": external_id, "sku_id": sku_id}],
        }
        if consume_request_no:
            body["consume_request_no"] = consume_request_no
        response = await self.http.post_json(
            "/channels/ec/voucher/revoke",
            body,
        )
        data = _first_voucher(
            response, {"code": external_id, "sku_id": sku_id, "status": 1}
        )
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
        self, product_id: str, bill_date: str, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        body: dict[str, Any] = {
            "product_id": product_id,
            "bill_date": bill_date,
            "page_size": 100,
            "page_ctx": cursor or "",
        }
        response = await self.http.post_json("/channels/ec/voucher/get_bill_list", body)
        values = response.get("bill_list", [])
        return [dict(item) for item in values if isinstance(item, Mapping)], response.get(
            "page_ctx"
        ) or None


__all__ = ["LiveLocalLifeGateway"]
