from __future__ import annotations

import json

import httpx
import pytest
import respx

from poi_admin.connections.local_life_live import LiveLocalLifeGateway
from poi_admin.connections.ports import GatewayTerminalError, GatewayTransientError
from poi_admin.connections.service_poi_live import LiveServicePoiGateway
from poi_admin.connections.tokens import StaticTokenProvider


def _reply(data: dict[str, object] | None = None) -> httpx.Response:
    return httpx.Response(200, json={"errcode": 0, **(data or {})})


@pytest.mark.asyncio
@respx.mock
async def test_local_life_gateway_covers_all_documented_operations() -> None:
    routes = {
        "add": respx.post("https://api.weixin.qq.com/channels/ec/product/locallife/add").mock(
            return_value=_reply(
                {
                    "data": {
                        "product_id": "p-1",
                        "product_name": "套餐",
                        "status": 0,
                        "sku_ids": ["sku-1"],
                    }
                }
            )
        ),
        "update": respx.post("https://api.weixin.qq.com/channels/ec/product/locallife/update").mock(
            return_value=_reply({"data": {"product_name": "updated", "status": 2}})
        ),
        "auditfree": respx.post(
            "https://api.weixin.qq.com/channels/ec/product/locallife/auditfree"
        ).mock(return_value=_reply({"data": {"product_name": "free", "status": 2}})),
        "get": respx.post("https://api.weixin.qq.com/channels/ec/product/locallife/get").mock(
            return_value=_reply({"online_data": {"product_name": "套餐", "status": 5}})
        ),
        "list": respx.post("https://api.weixin.qq.com/channels/ec/product/locallife/list/get").mock(
            return_value=_reply(
                {
                    "product_ids": [{"product_id": "p-1", "product_name": "套餐", "status": 3}],
                    "next_key": "next",
                }
            )
        ),
        "delete": respx.post("https://api.weixin.qq.com/channels/ec/product/delete").mock(
            return_value=_reply()
        ),
        "cancel": respx.post("https://api.weixin.qq.com/channels/ec/product/audit/cancel").mock(
            return_value=_reply()
        ),
        "listing": respx.post("https://api.weixin.qq.com/channels/ec/product/listing").mock(
            return_value=_reply()
        ),
        "delisting": respx.post("https://api.weixin.qq.com/channels/ec/product/delisting").mock(
            return_value=_reply()
        ),
        "stock": respx.post("https://api.weixin.qq.com/channels/ec/product/stock/update").mock(
            return_value=_reply({"stock": 8})
        ),
        "upload": respx.post("https://api.weixin.qq.com/channels/ec/voucher/codes/upload").mock(
            return_value=_reply({"accepted_count": 2})
        ),
        "order": respx.post("https://api.weixin.qq.com/channels/ec/order/get").mock(
            return_value=_reply({"order_info": {"order_status": "paid", "pay_amount": 1234}})
        ),
        "vouchers": respx.post("https://api.weixin.qq.com/channels/ec/voucher/get_list").mock(
            return_value=_reply({"voucher_list": [{"code": "v-1", "status": 1}]})
        ),
        "voucher": respx.post("https://api.weixin.qq.com/channels/ec/voucher/get").mock(
            return_value=_reply({"voucher": {"code": "v-1", "status": 1}})
        ),
        "consume": respx.post("https://api.weixin.qq.com/channels/ec/voucher/consume").mock(
            return_value=_reply(
                {"voucher_list": [{"code": "v-1", "status": 2, "out_store_id": "s-1"}]}
            )
        ),
        "revoke": respx.post("https://api.weixin.qq.com/channels/ec/voucher/revoke").mock(
            return_value=_reply({"voucher_list": [{"code": "v-1", "status": 1}]})
        ),
        "after_sale": respx.post(
            "https://api.weixin.qq.com/channels/ec/aftersale/getaftersaleorder"
        ).mock(return_value=_reply({"after_sale_order": {"id": "a-1", "status": "refunded"}})),
        "funds": respx.post("https://api.weixin.qq.com/channels/ec/funds/getfundsflowlist").mock(
            return_value=_reply({"funds": [{"id": "f-1"}], "next_key": "f-next"})
        ),
        "bills": respx.post("https://api.weixin.qq.com/channels/ec/voucher/get_bill_list").mock(
            return_value=_reply({"bill_list": [{"id": "b-1"}], "page_ctx": "b-next"})
        ),
    }
    gateway = LiveLocalLifeGateway(StaticTokenProvider("access"))

    product_payload = {
        "merchant_product_id": "merchant-1",
        "name": "套餐",
        "product_type": "cash_voucher",
        "category": "cat",
        "brand": "brand",
        "head_images": ["https://img"],
        "code_source": "wechat",
        "rules": {"refund_policy": "1"},
        "skus": [{"merchant_sku_id": "merchant-sku-1", "sale_price": 9900}],
    }
    created = await gateway.create_product(product_payload)
    updated = await gateway.update_product("p-1", {**product_payload, "name": "updated"})
    free = await gateway.audit_free_update_product("p-1", {**product_payload, "name": "free"})
    fetched = await gateway.get_product("p-1")
    products, next_cursor = await gateway.list_products("cursor")
    await gateway.delete_product("p-1")
    assert (await gateway.cancel_product_audit("p-1")).status == "draft"
    assert (await gateway.list_product("p-1")).status == "listed"
    assert (await gateway.delist_product("p-1")).status == "delisted"
    stock = await gateway.update_stock("p-1", "sku-1", 8)
    uploaded = await gateway.upload_voucher_codes("p-1", "sku-1", ["A", "B"])
    order = await gateway.get_order("order-1")
    vouchers = await gateway.list_vouchers("openid-1", status=1, cursor="voucher-cursor")
    voucher = await gateway.get_voucher("v-1", sku_id="sku-1")
    consumed = await gateway.consume_voucher(
        "v-1",
        sku_id="sku-1",
        consume_request_no="consume-1",
        out_store_id="s-1",
        consume_store_name="西湖门店",
        reserve_no="reserve-1",
    )
    revoked = await gateway.revoke_consumption(
        "v-1",
        sku_id="sku-1",
        revoke_request_no="revoke-1",
        consume_request_no="consume-1",
    )
    after_sale = await gateway.get_after_sale("a-1")
    funds, funds_cursor = await gateway.list_funds("f-cursor")
    bills, bills_cursor = await gateway.list_bills("p-1", "2026-08-24", "b-cursor")

    assert created.external_id == fetched.external_id == "p-1"
    assert updated.name == "updated" and free.name == "free"
    assert products[0].external_id == "p-1" and next_cursor == "next"
    assert stock["stock"] == 8 and uploaded["accepted_count"] == 2
    assert order.status == "paid" and order.total_amount == 1234
    assert vouchers[0].state == voucher.state == "available"
    assert consumed.state == "consumed" and revoked.state == "available"
    assert after_sale["id"] == "a-1"
    assert funds[0]["id"] == "f-1" and funds_cursor == "f-next"
    assert bills[0]["id"] == "b-1" and bills_cursor == "b-next"

    assert json.loads(routes["add"].calls[0].request.content) == {
        "out_product_id": "merchant-1",
        "product_type": 1,
        "product_name": "套餐",
        "category_id": "cat",
        "brand_id": "brand",
        "head_imgs": ["https://img"],
        "verify_at_store": 1,
        "code_source_type": 1,
        "attr_kv_map": {"refund_policy": "1"},
        "skus": [{"sale_price": 9900}],
    }
    assert json.loads(routes["list"].calls[0].request.content) == {
        "status": 0,
        "page_size": 30,
        "next_key": "cursor",
    }
    assert json.loads(routes["get"].calls[0].request.content) == {
        "product_id": "p-1",
        "data_type": 3,
    }
    assert json.loads(routes["update"].calls[0].request.content) == {
        "product_id": "p-1",
        "product_name": "updated",
        "out_product_id": "merchant-1",
        "product_type": 1,
        "category_id": "cat",
        "brand_id": "brand",
        "head_imgs": ["https://img"],
        "attr_kv_map": {"refund_policy": "1"},
        "skus": [{"sale_price": 9900}],
    }
    assert json.loads(routes["auditfree"].calls[0].request.content) == {
        "product_id": "p-1",
        "product_name": "free",
        "out_product_id": "merchant-1",
        "product_type": 1,
        "category_id": "cat",
        "brand_id": "brand",
        "head_imgs": ["https://img"],
        "attr_kv_map": {"refund_policy": "1"},
        "skus": [{"sale_price": 9900}],
    }
    for action in ("delete", "cancel", "listing", "delisting"):
        assert json.loads(routes[action].calls[0].request.content) == {"product_id": "p-1"}
    assert json.loads(routes["stock"].calls[0].request.content) == {
        "product_id": "p-1",
        "sku_id": "sku-1",
        "diff_type": 3,
        "num": 8,
    }
    assert json.loads(routes["upload"].calls[0].request.content) == {
        "product_id": "p-1",
        "sku_id": "sku-1",
        "codes": ["A", "B"],
    }
    assert json.loads(routes["order"].calls[0].request.content) == {"order_id": "order-1"}
    assert json.loads(routes["vouchers"].calls[0].request.content) == {
        "openid": "openid-1",
        "page_size": 50,
        "page_ctx": "voucher-cursor",
        "status": 1,
    }
    assert json.loads(routes["voucher"].calls[0].request.content) == {
        "code": "v-1",
        "sku_id": "sku-1",
    }
    assert json.loads(routes["consume"].calls[0].request.content) == {
        "consume_request_no": "consume-1",
        "codes": ["v-1"],
        "sku_id": "sku-1",
        "out_store_id": "s-1",
        "consume_channel": 2,
        "consume_store_name": "西湖门店",
        "reserve_no": "reserve-1",
    }
    assert json.loads(routes["revoke"].calls[0].request.content) == {
        "revoke_request_no": "revoke-1",
        "reovke_vouchers": [{"code": "v-1", "sku_id": "sku-1"}],
        "consume_request_no": "consume-1",
    }
    assert json.loads(routes["funds"].calls[0].request.content) == {
        "page": 1,
        "page_size": 50,
        "next_key": "f-cursor",
    }
    assert json.loads(routes["bills"].calls[0].request.content) == {
        "product_id": "p-1",
        "bill_date": "2026-08-24",
        "page_size": 100,
        "page_ctx": "b-cursor",
    }
    assert json.loads(routes["after_sale"].calls[0].request.content) == {
        "after_sale_order_id": "a-1",
    }


@pytest.mark.asyncio
@respx.mock
async def test_service_poi_gateway_covers_list_crud_and_audit_request_shapes() -> None:
    routes = {
        "list": respx.post("https://api.weixin.qq.com/wxa/get_store_list").mock(
            return_value=_reply(
                {
                    "business_list": [
                        {
                            "base_info": {
                                "poi_id": "poi-1",
                                "business_name": "门店",
                                "address": "地址",
                                "latitude": "30.1",
                                "longitude": 120.2,
                            }
                        }
                    ]
                }
            )
        ),
        "get": respx.post("https://api.weixin.qq.com/wxa/get_store_info").mock(
            return_value=_reply(
                {
                    "business": {
                        "poi_id": "poi-1",
                        "business_name": "门店",
                        "address": "地址",
                        "status": "approved",
                    }
                }
            )
        ),
        "search": respx.post("https://api.weixin.qq.com/wxa/search_map_poi").mock(
            return_value=_reply(
                {
                    "data": {
                        "item": [
                            {
                                "sosomap_poi_uid": "poi-2",
                                "branch_name": "搜索门店",
                                "address": "街道",
                            }
                        ]
                    }
                }
            )
        ),
        "create": respx.post("https://api.weixin.qq.com/wxa/create_map_poi").mock(
            return_value=_reply({"data": {"base_id": "base-3", "rich_id": "rich-3"}})
        ),
        "add_store": respx.post("https://api.weixin.qq.com/wxa/add_store").mock(
            return_value=_reply({"data": {"audit_id": "audit-4"}})
        ),
        "update": respx.post("https://api.weixin.qq.com/wxa/update_store").mock(
            return_value=_reply({"data": {"status": "approved"}})
        ),
        "delete": respx.post("https://api.weixin.qq.com/wxa/del_store").mock(return_value=_reply()),
    }
    gateway = LiveServicePoiGateway(StaticTokenProvider("access"), district_id=3205)

    listed = await gateway.list_pois("50")
    fetched = await gateway.get_poi("poi-1")
    searched = await gateway.search_pois("咖啡")
    created = await gateway.create_poi(
        {
            "name": "新店",
            "address": "新地址",
            "longitude": 120.2,
            "latitude": 30.1,
            "province": "浙江省",
            "city": "杭州市",
            "district": "西湖区",
            "category": "美食:中餐厅",
            "telephone": "13800138000",
            "photo": "https://example.com/store.jpg",
            "license": "https://example.com/license.jpg",
            "description": "简介",
            "districtid": 3205,
        }
    )
    submitted = await gateway.create_poi(
        {
            "map_poi_id": "map-poi-4",
            "name": "新店",
            "address": "新地址",
            "pic_list": ["https://example.com/store.jpg"],
            "contract_phone": "13800138000",
            "hour": "09:00-21:00",
            "credential": "license-1",
            "company_name": "杭州示例公司",
        }
    )
    updated = await gateway.update_poi(
        "poi-3",
        {
            "map_poi_id": "map-1",
            "contract_phone": "139",
            "hour": "9-18",
            "card_id": "card",
            "pic_list": ["a", "b"],
            "ignored": "x",
        },
    )
    await gateway.delete_poi("poi-3")
    status = await gateway.get_audit_status("poi-1")

    assert listed[0].poi_id == fetched.poi_id == "poi-1"
    assert searched[0].poi_id == "poi-2"
    assert created.poi_id == "map:base-3:rich-3" and created.status == "map_pending"
    assert submitted.poi_id == "audit:audit-4" and submitted.status == "under_review"
    assert updated.poi_id == "poi-3" and status == "approved"
    assert json.loads(routes["list"].calls[0].request.content) == {"offset": 50, "limit": 50}
    assert json.loads(routes["get"].calls[0].request.content) == {"poi_id": "poi-1"}
    assert json.loads(routes["search"].calls[0].request.content) == {
        "districtid": 3205,
        "keyword": "咖啡",
    }
    assert json.loads(routes["create"].calls[0].request.content) == {
        "name": "新店",
        "longitude": "120.2",
        "latitude": "30.1",
        "province": "浙江省",
        "city": "杭州市",
        "district": "西湖区",
        "address": "新地址",
        "category": "美食:中餐厅",
        "telephone": "13800138000",
        "photo": "https://example.com/store.jpg",
        "license": "https://example.com/license.jpg",
        "introduct": "简介",
        "districtid": 3205,
    }
    assert json.loads(routes["add_store"].calls[0].request.content) == {
        "map_poi_id": "map-poi-4",
        "pic_list": '{"list": ["https://example.com/store.jpg"]}',
        "contract_phone": "13800138000",
        "hour": "09:00-21:00",
        "credential": "license-1",
        "company_name": "杭州示例公司",
        "card_id": "",
    }
    assert json.loads(routes["update"].calls[0].request.content) == {
        "poi_id": "poi-3",
        "map_poi_id": "map-1",
        "contract_phone": "139",
        "hour": "9-18",
        "card_id": "card",
        "pic_list": '["a", "b"]',
    }


@pytest.mark.asyncio
@respx.mock
async def test_live_adapter_preserves_terminal_and_transient_wechat_errors() -> None:
    respx.post("https://api.weixin.qq.com/channels/ec/order/get").mock(
        return_value=_reply({"errcode": 40013, "errmsg": "invalid appid"})
    )
    with pytest.raises(GatewayTerminalError) as terminal:
        await LiveLocalLifeGateway(StaticTokenProvider("access")).get_order("o-1")
    assert terminal.value.code == "wechat_40013" and not terminal.value.retryable

    respx.post("https://api.weixin.qq.com/wxa/get_store_list").mock(
        return_value=httpx.Response(503, text="down")
    )
    with pytest.raises(GatewayTransientError) as transient:
        await LiveServicePoiGateway(StaticTokenProvider("access")).list_pois()
    assert transient.value.retryable


@pytest.mark.asyncio
@respx.mock
async def test_voucher_code_upload_preserves_partial_success_details() -> None:
    respx.post("https://api.weixin.qq.com/channels/ec/voucher/codes/upload").mock(
        return_value=httpx.Response(
            200,
            json={
                "errcode": 10001,
                "errmsg": "partial success",
                "success_count": 1,
                "fail_count": 1,
                "fail_list": [{"code": "DUPLICATE", "errcode": 10002}],
            },
        )
    )

    result = await LiveLocalLifeGateway(StaticTokenProvider("access")).upload_voucher_codes(
        "product-1", "sku-1", ["GOOD", "DUPLICATE"]
    )

    assert result["accepted_count"] == 1
    assert result["failed_count"] == 1
    assert result["fail_list"] == [{"code": "DUPLICATE", "errcode": 10002}]
