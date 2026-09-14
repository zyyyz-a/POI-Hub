from __future__ import annotations

import pytest
from httpx import AsyncClient
from tests.direct_commerce.test_direct_commerce_routes import ready_mini_program
from tests.onboarding.test_onboarding_routes import create_store, login


async def _commerce_connection_id(client: AsyncClient, tenant_id: str) -> str:
    response = await client.get(
        "/api/v1/connections", headers={"X-Tenant-ID": tenant_id}
    )
    assert response.status_code == 200, response.text
    for item in response.json():
        if item["capability"] == "mini_program_commerce":
            return str(item["id"])
    raise AssertionError("commerce connection missing")


async def _tenant_store_with_product(
    client: AsyncClient, csrf: str, tenant_id: str, *, product_name: str, product_code: str
) -> dict[str, str]:
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    store_id = await create_store(client, csrf, tenant_id)
    mini_program_id, _ = await ready_mini_program(client, csrf, tenant_id, store_id)
    product = await client.post(
        "/api/v1/direct-commerce/products",
        headers=headers,
        json={
            "mini_program_id": mini_program_id,
            "store_id": store_id,
            "merchant_product_id": product_code,
            "name": product_name,
            "sale_price": 9900,
            "market_price": 12900,
            "stock": 10,
        },
    )
    assert product.status_code == 201, product.text
    listed = await client.patch(
        f"/api/v1/direct-commerce/products/{product.json()['id']}",
        headers=headers,
        json={"version": product.json()["version"], "status": "listed"},
    )
    assert listed.status_code == 200, listed.text
    return {
        "store_id": store_id,
        "mini_program_id": mini_program_id,
        "product_id": product.json()["id"],
        "connection_id": await _commerce_connection_id(client, tenant_id),
    }


async def _create_binding(
    client: AsyncClient, csrf: str, tenant_id: str, program_id: str, store_id: str, store_code: str
) -> dict[str, object]:
    created = await client.post(
        "/api/v1/store-bindings",
        headers={"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id},
        json={
            "platform_mini_program_id": program_id,
            "store_id": store_id,
            "store_code": store_code,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _activate_binding(
    client: AsyncClient,
    csrf: str,
    tenant_id: str,
    binding: dict[str, object],
    store_code: str,
) -> None:
    activated = await client.patch(
        f"/api/v1/store-bindings/{binding['id']}",
        headers={"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id},
        json={
            "version": binding["version"],
            "status": "active",
            "tencent_poi_id": f"TX-{store_code}",
            "official_reference": f"approval-{store_code}",
            "evidence_reference": f"evidence/{store_code}",
        },
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"


async def _active_payment_profile(
    client: AsyncClient, csrf: str, tenant_id: str, store_id: str, connection_id: str
) -> None:
    response = await client.post(
        "/api/v1/direct-commerce/payment-profiles",
        headers={"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id},
        json={
            "store_id": store_id,
            "connection_id": connection_id,
            "mode": "ordinary",
            "mchid": "1900000109",
            "verified": True,
            "status": "active",
        },
    )
    assert response.status_code == 201, response.text


async def _platform_program(client: AsyncClient, csrf: str, connection_id: str) -> str:
    created = await client.post(
        "/api/v1/platform/mini-programs",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "POI Hub 平台小程序",
            "owner_subject": "平台主体",
            "app_id": "wx-platform-001",
            "connection_id": connection_id,
            "callback_configured": True,
        },
    )
    assert created.status_code == 201, created.text
    activated = await client.patch(
        f"/api/v1/platform/mini-programs/{created.json()['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"version": created.json()["version"], "status": "active"},
    )
    assert activated.status_code == 200, activated.text
    return str(created.json()["id"])


@pytest.mark.asyncio
async def test_one_platform_appid_isolates_two_tenant_stores(client: AsyncClient) -> None:
    csrf, tenant_a = await login(client)
    tenant_b = (
        await client.post(
            "/api/v1/platform/tenants",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Tenant B", "slug": "tenant-b"},
        )
    ).json()["id"]

    store_a = await _tenant_store_with_product(
        client, csrf, tenant_a, product_name="A店染发", product_code="A-HAIR-001"
    )
    store_b = await _tenant_store_with_product(
        client, csrf, tenant_b, product_name="B店烫发", product_code="B-HAIR-001"
    )
    program_id = await _platform_program(client, csrf, store_a["connection_id"])
    binding_a = await _create_binding(
        client, csrf, tenant_a, program_id, store_a["store_id"], "store-a"
    )
    await _activate_binding(client, csrf, tenant_a, binding_a, "store-a")
    binding_b = await _create_binding(
        client, csrf, tenant_b, program_id, store_b["store_id"], "store-b"
    )
    await _activate_binding(client, csrf, tenant_b, binding_b, "store-b")
    await _active_payment_profile(
        client, csrf, tenant_a, store_a["store_id"], store_a["connection_id"]
    )
    await _active_payment_profile(
        client, csrf, tenant_b, store_b["store_id"], store_b["connection_id"]
    )

    entry_a = await client.get("/api/v1/public/platform/stores/store-a")
    entry_b = await client.get("/api/v1/public/platform/stores/store-b")
    assert entry_a.json()["tradable"] is True, entry_a.text
    assert entry_b.json()["tradable"] is True, entry_b.text
    assert entry_a.json()["store_code"] == "store-a"
    assert entry_b.json()["store_code"] == "store-b"

    products_a = await client.get("/api/v1/public/platform/stores/store-a/products")
    products_b = await client.get("/api/v1/public/platform/stores/store-b/products")
    assert [item["name"] for item in products_a.json()] == ["A店染发"]
    assert [item["name"] for item in products_b.json()] == ["B店烫发"]

    login_a = await client.post(
        "/api/v1/public/platform/stores/store-a/login", json={"code": "code-a"}
    )
    assert login_a.status_code == 200, login_a.text
    consumer_headers = {"Authorization": "Bearer " + login_a.json()["access_token"]}

    order = await client.post(
        "/api/v1/public/platform/stores/store-a/orders",
        headers=consumer_headers,
        json={
            "product_id": store_a["product_id"],
            "quantity": 1,
            "idempotency_key": "platform-order-0001",
        },
    )
    assert order.status_code == 201, order.text
    paid = await client.post(
        f"/api/v1/public/platform/stores/store-a/orders/{order.json()['id']}/pay",
        headers=consumer_headers,
        json={},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["order"]["status"] == "paid"

    cross_product = await client.post(
        "/api/v1/public/platform/stores/store-b/orders",
        headers=consumer_headers,
        json={
            "product_id": store_a["product_id"],
            "quantity": 1,
            "idempotency_key": "platform-order-cross",
        },
    )
    assert cross_product.status_code == 409
    assert cross_product.json()["detail"]["code"] == "product_not_available"

    leaked_order = await client.get(
        f"/api/v1/public/platform/stores/store-b/orders/{order.json()['id']}",
        headers=consumer_headers,
    )
    assert leaked_order.status_code == 404


@pytest.mark.asyncio
async def test_entry_is_blocked_until_binding_activated(client: AsyncClient) -> None:
    csrf, tenant_id = await login(client)
    store = await _tenant_store_with_product(
        client, csrf, tenant_id, product_name="待上线套餐", product_code="WAIT-001"
    )
    program_id = await _platform_program(client, csrf, store["connection_id"])
    await _active_payment_profile(
        client, csrf, tenant_id, store["store_id"], store["connection_id"]
    )
    created = await client.post(
        "/api/v1/store-bindings",
        headers={"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id},
        json={
            "platform_mini_program_id": program_id,
            "store_id": store["store_id"],
            "store_code": "store-draft",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"

    entry = await client.get("/api/v1/public/platform/stores/store-draft")
    assert entry.status_code == 200, entry.text
    assert entry.json()["tradable"] is False
    assert "门店入口未启用" in entry.json()["blockers"]

    blocked_login = await client.post(
        "/api/v1/public/platform/stores/store-draft/login", json={"code": "code-x"}
    )
    assert blocked_login.status_code == 409
    assert blocked_login.json()["detail"]["code"] == "store_not_tradable"

    await _activate_binding(client, csrf, tenant_id, created.json(), "store-draft")
    ready = await client.get("/api/v1/public/platform/stores/store-draft")
    assert ready.json()["tradable"] is True, ready.text
