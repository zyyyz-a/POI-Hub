from __future__ import annotations

import json

import httpx
import pytest
import respx

from poi_admin.connections.local_life_live import LiveLocalLifeGateway
from poi_admin.connections.ports import GatewayTransientError
from poi_admin.connections.service_poi_live import LiveServicePoiGateway
from poi_admin.connections.tokens import StaticTokenProvider


@pytest.mark.asyncio
@respx.mock
async def test_local_life_product_list_uses_access_token_and_cursor() -> None:
    route = respx.post("https://api.weixin.qq.com/channels/ec/product/locallife/list/get").mock(
        return_value=httpx.Response(
            200,
            json={
                "errcode": 0,
                "data": {
                    "products": [{"product_id": "remote-1", "product_name": "套餐", "status": 3}],
                    "next_cursor": "next-1",
                },
            },
        )
    )
    gateway = LiveLocalLifeGateway(StaticTokenProvider("test-access-token"))

    products, next_cursor = await gateway.list_products(cursor="cursor-1")

    assert route.called
    assert route.calls[0].request.url.params["access_token"] == "test-access-token"
    assert json.loads(route.calls[0].request.content) == {
        "status": 0,
        "page_size": 30,
        "next_key": "cursor-1",
    }
    assert products[0].external_id == "remote-1"
    assert next_cursor == "next-1"


@pytest.mark.asyncio
@respx.mock
async def test_service_poi_search_uses_documented_map_endpoint() -> None:
    route = respx.post("https://api.weixin.qq.com/wxa/search_map_poi").mock(
        return_value=httpx.Response(
            200,
            json={
                "errcode": 0,
                "data": {
                    "item": [
                        {
                            "sosomap_poi_uid": "poi-1",
                            "branch_name": "门店",
                            "address": "地址",
                            "latitude": 30.1,
                            "longitude": 120.1,
                        }
                    ]
                },
            },
        )
    )
    gateway = LiveServicePoiGateway(StaticTokenProvider("test-access-token"))

    pois = await gateway.search_pois("门店")

    assert route.called
    assert route.calls[0].request.url.params["access_token"] == "test-access-token"
    assert json.loads(route.calls[0].request.content) == {"districtid": 0, "keyword": "门店"}
    assert pois[0].poi_id == "poi-1"


@pytest.mark.asyncio
@respx.mock
async def test_http_error_is_classified_as_retryable() -> None:
    respx.post("https://api.weixin.qq.com/channels/ec/product/locallife/list/get").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    gateway = LiveLocalLifeGateway(StaticTokenProvider("test-access-token"))

    with pytest.raises(GatewayTransientError, match="upstream") as caught:
        await gateway.list_products()

    assert getattr(caught.value, "retryable", False) is True
