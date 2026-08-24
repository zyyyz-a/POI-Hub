from __future__ import annotations

import pytest

from poi_admin.connections.mock import MockLocalLifeGateway, MockServicePoiGateway
from poi_admin.connections.ports import LocalLifeGateway, ServicePoiGateway


@pytest.mark.asyncio
async def test_mock_gateways_implement_typed_contracts() -> None:
    local: LocalLifeGateway = MockLocalLifeGateway("tenant-a")
    poi: ServicePoiGateway = MockServicePoiGateway("tenant-a")

    product = await local.create_product({"name": "团购套餐", "merchant_product_id": "p-1"})
    assert product.external_id.startswith("mock-product-")
    assert (await local.get_product(product.external_id)).external_id == product.external_id
    await local.update_product(product.external_id, {"name": "新名称"})
    await local.audit_free_update_product(product.external_id, {"name": "免审更新"})
    await local.update_stock(product.external_id, "sku-1", 10)
    assert (await local.upload_voucher_codes(product.external_id, "sku-1", ["A", "B"]))[
        "accepted_count"
    ] == 2
    assert (await local.cancel_product_audit(product.external_id)).status == "draft"
    assert (await local.list_product(product.external_id)).status == "listed"
    assert (await local.delist_product(product.external_id)).status == "delisted"
    assert (await local.list_products())[0]
    order = await local.get_order("order-1")
    assert order.status == "paid"
    voucher = (await local.list_vouchers("openid-1"))[0]
    consumed = await local.consume_voucher(
        voucher.external_id,
        sku_id="sku-1",
        consume_request_no="consume-1",
        out_store_id="store-1",
    )
    assert consumed.state == "consumed"
    assert (
        await local.revoke_consumption(
            voucher.external_id,
            sku_id="sku-1",
            revoke_request_no="revoke-1",
            consume_request_no="consume-1",
        )
    ).state == "available"
    assert (await local.get_after_sale("after-sale-1"))["status"] == "none"
    assert (await local.list_funds())[0]
    assert (await local.list_bills("product-1", "2026-08-24"))[0]
    pois = await poi.list_pois()
    assert pois and pois[0].poi_id.startswith("mock-poi-")
    assert (await poi.get_poi(pois[0].poi_id)).poi_id == pois[0].poi_id
    assert await poi.search_pois("西湖")
    created = await poi.create_poi({"name": "新门店", "address": "新地址"})
    assert (await poi.update_poi(created.poi_id, {"name": "更新门店"})).name == "更新门店"
    assert await poi.get_audit_status(created.poi_id) == "pending"
    await poi.delete_poi(created.poi_id)
    await local.delete_product(product.external_id)


@pytest.mark.asyncio
async def test_mock_scenario_can_raise_deterministic_failure() -> None:
    gateway = MockLocalLifeGateway("tenant-a", scenario="rate_limit")
    with pytest.raises(Exception, match="rate limit"):
        await gateway.get_order("order-1")
