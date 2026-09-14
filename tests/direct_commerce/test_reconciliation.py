from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from tests.direct_commerce.test_refunds import _buy_and_pay, _ready_store
from tests.onboarding.test_onboarding_routes import login

from poi_admin.direct_commerce.reconciliation import parse_trade_bill_csv

SAMPLE_BILL = (
    "交易时间,公众账号ID,商户号,微信订单号,商户订单号,交易状态,订单金额,退款金额,商户退款单号\n"
    "2026-09-14 10:00:00,wxapp,1900000109,TX001,ORDER-A,SUCCESS,99.00,0.00,\n"
    "2026-09-14 10:05:00,wxapp,1900000109,TX002,ORDER-B,SUCCESS,50.00,0.00,\n"
    "总交易单数,2,,,,,,\n"
)


def test_parse_trade_bill_csv_normalizes_amounts() -> None:
    rows = parse_trade_bill_csv(SAMPLE_BILL)
    assert [row.order_no for row in rows] == ["ORDER-A", "ORDER-B"]
    assert rows[0].amount == 9900
    assert rows[0].transaction_id == "TX001"
    assert rows[0].trade_state == "SUCCESS"


async def _order_numbers(client: AsyncClient, tenant_id: str) -> dict[str, str]:
    response = await client.get(
        "/api/v1/direct-commerce/orders", headers={"X-Tenant-ID": tenant_id}
    )
    assert response.status_code == 200, response.text
    return {item["id"]: item["order_no"] for item in response.json()}


@pytest.mark.asyncio
async def test_reconciliation_import_flags_all_difference_types(client: AsyncClient) -> None:
    csrf, tenant_id = await login(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    store = await _ready_store(
        client, csrf, tenant_id, store_code="store-recon", product_code="REC-001"
    )
    _, order_a, _ = await _buy_and_pay(client, "store-recon", store, key="recon-order-a")
    _, order_b, _ = await _buy_and_pay(client, "store-recon", store, key="recon-order-b")
    await _buy_and_pay(client, "store-recon", store, key="recon-order-c")
    numbers = await _order_numbers(client, tenant_id)

    bill_date = datetime.now(UTC).strftime("%Y-%m-%d")
    csv = (
        "交易时间,公众账号ID,商户号,微信订单号,商户订单号,交易状态,订单金额,退款金额,商户退款单号\n"
        f"2026-09-14 10:00:00,wxapp,1900000109,TXA,{numbers[order_a]},SUCCESS,99.00,0.00,\n"
        f"2026-09-14 10:05:00,wxapp,1900000109,TXB,{numbers[order_b]},SUCCESS,50.00,0.00,\n"
        "2026-09-14 10:10:00,wxapp,1900000109,TXC,PF-UNKNOWN-ORDER,SUCCESS,10.00,0.00,\n"
    )
    imported = await client.post(
        "/api/v1/direct-commerce/reconciliation/import",
        headers=headers,
        json={"bill_date": bill_date, "csv": csv},
    )
    assert imported.status_code == 201, imported.text
    batch = imported.json()
    assert batch["statement_total"] == 9900 + 5000 + 1000
    assert batch["matched_count"] == 1
    assert batch["difference_count"] == 3

    items = await client.get(
        f"/api/v1/direct-commerce/reconciliation/batches/{batch['id']}/items",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert items.status_code == 200, items.text
    by_order = {item["order_no"]: item for item in items.json()}
    assert by_order[numbers[order_a]]["status"] == "matched"
    assert by_order[numbers[order_b]]["status"] == "amount_mismatch"
    assert by_order["PF-UNKNOWN-ORDER"]["status"] == "missing_platform"
    assert any(item["status"] == "missing_statement" for item in items.json())

    mismatch = by_order[numbers[order_b]]
    resolved = await client.post(
        f"/api/v1/direct-commerce/reconciliation/items/{mismatch['id']}/resolve",
        headers=headers,
        json={"note": "已核对，差异为补差金额未入账"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["resolved"] is True

    duplicate = await client.post(
        "/api/v1/direct-commerce/reconciliation/import",
        headers=headers,
        json={"bill_date": bill_date, "csv": csv},
    )
    assert duplicate.status_code == 409
