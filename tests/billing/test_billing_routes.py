from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from tests.direct_commerce.test_refunds import _ready_store
from tests.onboarding.test_onboarding_routes import login


async def _create_plan(client: AsyncClient, csrf: str, *, price: int = 10000) -> dict[str, object]:
    response = await client.post(
        "/api/v1/billing/plans",
        headers={"X-CSRF-Token": csrf},
        json={
            "code": "saas-basic",
            "name": "基础版",
            "price": price,
            "billing_period": "monthly",
            "period_days": 30,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_billing_lifecycle_usage_invoice_payment_and_adjustment(
    client: AsyncClient,
) -> None:
    csrf, tenant_id = await login(client)
    plan = await _create_plan(client, csrf)

    subscription = await client.post(
        "/api/v1/billing/subscriptions",
        headers={"X-CSRF-Token": csrf},
        json={"tenant_id": tenant_id, "plan_id": plan["id"], "grace_days": 7},
    )
    assert subscription.status_code == 201, subscription.text
    assert subscription.json()["status"] == "active"

    usage_body = {
        "tenant_id": tenant_id,
        "event_type": "store_message",
        "quantity": 3,
        "unit_amount": 100,
        "idempotency_key": "usage-event-0001",
    }
    usage = await client.post(
        "/api/v1/billing/usage-events", headers={"X-CSRF-Token": csrf}, json=usage_body
    )
    assert usage.status_code == 201, usage.text
    assert usage.json()["amount"] == 300
    duplicate = await client.post(
        "/api/v1/billing/usage-events", headers={"X-CSRF-Token": csrf}, json=usage_body
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == usage.json()["id"]

    start = datetime.now(UTC) - timedelta(days=1)
    invoice = await client.post(
        "/api/v1/billing/invoices",
        headers={"X-CSRF-Token": csrf},
        json={
            "tenant_id": tenant_id,
            "period_start": start.isoformat(),
            "period_end": (start + timedelta(days=30)).isoformat(),
        },
    )
    assert invoice.status_code == 201, invoice.text
    assert invoice.json()["amount"] == 300
    invoice_id = invoice.json()["id"]

    items = await client.get(
        f"/api/v1/billing/invoices/{invoice_id}/items", headers={"X-Tenant-ID": tenant_id}
    )
    assert items.status_code == 200, items.text
    assert items.json()[0]["source_type"] == "usage"

    partial = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/payments",
        headers={"X-CSRF-Token": csrf},
        json={"amount": 100, "method": "bank_transfer"},
    )
    assert partial.status_code == 201, partial.text

    overpay = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/payments",
        headers={"X-CSRF-Token": csrf},
        json={"amount": 500, "method": "bank_transfer"},
    )
    assert overpay.status_code == 422
    assert overpay.json()["detail"]["code"] == "overpayment"

    paid = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/payments",
        headers={"X-CSRF-Token": csrf},
        json={"amount": 200, "method": "payment_code"},
    )
    assert paid.status_code == 201, paid.text

    invoices = await client.get("/api/v1/billing/invoices", headers={"X-Tenant-ID": tenant_id})
    assert invoices.json()[0]["status"] == "paid"

    adjustment = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/adjustments",
        headers={"X-CSRF-Token": csrf},
        json={"kind": "discount", "amount": -50, "reason": "首月优惠"},
    )
    assert adjustment.status_code == 201, adjustment.text

    summary = await client.get("/api/v1/billing/summary", headers={"X-Tenant-ID": tenant_id})
    assert summary.status_code == 200, summary.text
    assert summary.json()["blocked"] is False
    assert summary.json()["outstanding_amount"] == 0


@pytest.mark.asyncio
async def test_expired_subscription_blocks_store_entry(client: AsyncClient) -> None:
    csrf, tenant_id = await login(client)
    plan = await _create_plan(client, csrf, price=9900)
    store = await _ready_store(
        client, csrf, tenant_id, store_code="store-billing", product_code="BILL-001"
    )
    entry = await client.get("/api/v1/public/platform/stores/store-billing")
    assert entry.json()["tradable"] is True, entry.text

    subscription = await client.post(
        "/api/v1/billing/subscriptions",
        headers={"X-CSRF-Token": csrf},
        json={
            "tenant_id": tenant_id,
            "plan_id": plan["id"],
            "period_start": (datetime.now(UTC) - timedelta(days=60)).isoformat(),
            "grace_days": 7,
        },
    )
    assert subscription.status_code == 201, subscription.text

    blocked = await client.get("/api/v1/billing/summary", headers={"X-Tenant-ID": tenant_id})
    assert blocked.json()["blocked"] is True
    assert "商户订阅已过期且超出宽限期" in blocked.json()["blockers"]

    suspended = await client.patch(
        f"/api/v1/billing/subscriptions/{subscription.json()['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"status": "suspended", "version": subscription.json()["version"]},
    )
    assert suspended.status_code == 200, suspended.text

    entry_after = await client.get("/api/v1/public/platform/stores/store-billing")
    assert entry_after.json()["tradable"] is False
    assert "商户订阅已停用" in entry_after.json()["blockers"]
    assert store["store_id"]
