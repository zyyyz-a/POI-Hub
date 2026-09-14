from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from tests.direct_commerce.test_platform_entry import (
    _activate_binding,
    _active_payment_profile,
    _create_binding,
    _platform_program,
    _tenant_store_with_product,
)
from tests.onboarding.test_onboarding_routes import login

from poi_admin.direct_commerce.models import DirectOrder
from poi_admin.direct_commerce.service import DirectCommerceService


async def _ready_store(
    client: AsyncClient, csrf: str, tenant_id: str, *, store_code: str, product_code: str
) -> dict[str, str]:
    store = await _tenant_store_with_product(
        client, csrf, tenant_id, product_name="退款套餐", product_code=product_code
    )
    program_id = await _platform_program(client, csrf, store["connection_id"])
    binding = await _create_binding(
        client, csrf, tenant_id, program_id, store["store_id"], store_code
    )
    await _activate_binding(client, csrf, tenant_id, binding, store_code)
    await _active_payment_profile(
        client, csrf, tenant_id, store["store_id"], store["connection_id"]
    )
    return store


async def _buy_and_pay(
    client: AsyncClient, store_code: str, store: dict[str, str], *, key: str
) -> tuple[dict[str, str], str, int]:
    login_response = await client.post(
        f"/api/v1/public/platform/stores/{store_code}/login", json={"code": "buyer-" + key}
    )
    consumer_headers = {"Authorization": "Bearer " + login_response.json()["access_token"]}
    order = await client.post(
        f"/api/v1/public/platform/stores/{store_code}/orders",
        headers=consumer_headers,
        json={"product_id": store["product_id"], "quantity": 1, "idempotency_key": key},
    )
    assert order.status_code == 201, order.text
    total = order.json()["total_amount"]
    paid = await client.post(
        f"/api/v1/public/platform/stores/{store_code}/orders/{order.json()['id']}/pay",
        headers=consumer_headers,
        json={},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["order"]["status"] == "paid"
    return consumer_headers, order.json()["id"], total


@pytest.mark.asyncio
async def test_full_refund_revokes_voucher_and_restores_stock(client: AsyncClient) -> None:
    csrf, tenant_id = await login(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    store = await _ready_store(
        client, csrf, tenant_id, store_code="store-refund", product_code="RF-001"
    )
    consumer_headers, order_id, total = await _buy_and_pay(
        client, "store-refund", store, key="refund-order-0001"
    )
    appointment = await client.post(
        f"/api/v1/public/platform/stores/store-refund/orders/{order_id}/appointment",
        headers=consumer_headers,
        json={
            "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "contact_name": "退款顾客",
            "contact_phone": "13900000000",
        },
    )
    assert appointment.status_code == 201, appointment.text

    refund = await client.post(
        f"/api/v1/direct-commerce/orders/{order_id}/refunds",
        headers=headers,
        json={"amount": total, "reason": "顾客取消", "idempotency_key": "refund-key-0001"},
    )
    assert refund.status_code == 201, refund.text
    assert refund.json()["status"] == "success"

    orders = await client.get("/api/v1/direct-commerce/orders", headers={"X-Tenant-ID": tenant_id})
    order_row = next(item for item in orders.json() if item["id"] == order_id)
    assert order_row["status"] == "refunded"

    vouchers = await client.get(
        "/api/v1/direct-commerce/vouchers", headers={"X-Tenant-ID": tenant_id}
    )
    voucher_row = next(item for item in vouchers.json() if item["order_id"] == order_id)
    assert voucher_row["state"] == "refunded"

    appointments = await client.get(
        "/api/v1/direct-commerce/appointments", headers={"X-Tenant-ID": tenant_id}
    )
    appointment_row = next(item for item in appointments.json() if item["order_id"] == order_id)
    assert appointment_row["status"] == "cancelled"

    products = await client.get("/api/v1/public/platform/stores/store-refund/products")
    assert products.json()[0]["stock"] == 10


@pytest.mark.asyncio
async def test_partial_refund_keeps_voucher_and_is_idempotent(client: AsyncClient) -> None:
    csrf, tenant_id = await login(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    store = await _ready_store(
        client, csrf, tenant_id, store_code="store-partial", product_code="RF-002"
    )
    _, order_id, total = await _buy_and_pay(
        client, "store-partial", store, key="refund-order-0002"
    )
    body = {
        "amount": total // 2,
        "reason": "部分补偿",
        "idempotency_key": "refund-key-0002",
    }
    first = await client.post(
        f"/api/v1/direct-commerce/orders/{order_id}/refunds", headers=headers, json=body
    )
    assert first.status_code == 201, first.text
    repeated = await client.post(
        f"/api/v1/direct-commerce/orders/{order_id}/refunds", headers=headers, json=body
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == first.json()["id"]

    conflict = await client.post(
        f"/api/v1/direct-commerce/orders/{order_id}/refunds",
        headers=headers,
        json={**body, "amount": total // 4},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"

    orders = await client.get("/api/v1/direct-commerce/orders", headers={"X-Tenant-ID": tenant_id})
    order_row = next(item for item in orders.json() if item["id"] == order_id)
    assert order_row["status"] == "partially_refunded"

    vouchers = await client.get(
        "/api/v1/direct-commerce/vouchers", headers={"X-Tenant-ID": tenant_id}
    )
    voucher_row = next(item for item in vouchers.json() if item["order_id"] == order_id)
    assert voucher_row["state"] == "available"


@pytest.mark.asyncio
async def test_expired_order_is_closed_and_stock_released(client: AsyncClient) -> None:
    csrf, tenant_id = await login(client)
    store = await _ready_store(
        client, csrf, tenant_id, store_code="store-expire", product_code="RF-003"
    )
    login_response = await client.post(
        "/api/v1/public/platform/stores/store-expire/login", json={"code": "expire-buyer"}
    )
    consumer_headers = {"Authorization": "Bearer " + login_response.json()["access_token"]}
    order = await client.post(
        "/api/v1/public/platform/stores/store-expire/orders",
        headers=consumer_headers,
        json={
            "product_id": store["product_id"],
            "quantity": 1,
            "idempotency_key": "refund-order-0003",
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        row = (
            await session.execute(select(DirectOrder).where(DirectOrder.id == order_id))
        ).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    async with database.session_factory() as session:
        settings = client._transport.app.state.settings  # type: ignore[attr-defined]
        result = await DirectCommerceService(session, settings).run_maintenance()
    assert result["closed_orders"] == 1

    async with database.session_factory() as session:
        refreshed = (
            await session.execute(select(DirectOrder).where(DirectOrder.id == order_id))
        ).scalar_one()
        assert refreshed.status == "expired"

    products = await client.get("/api/v1/public/platform/stores/store-expire/products")
    assert products.json()[0]["stock"] == 10
