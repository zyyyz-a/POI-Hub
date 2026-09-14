from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from tests.onboarding.test_onboarding_routes import (
    create_store,
    login,
    qualification_items,
)

from poi_admin.stores.models import ServicePoi


async def ready_mini_program(
    client: AsyncClient, csrf: str, tenant_id: str, store_id: str
) -> tuple[str, str]:
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    commerce_connection = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={
            "capability": "mini_program_commerce",
            "mode": "mock",
            "app_id": "wx-direct-test",
            "merchant_id": "1900000109",
        },
    )
    assert commerce_connection.status_code == 201, commerce_connection.text
    poi_connection = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={"capability": "service_poi", "mode": "mock", "app_id": "wx-poi-test"},
    )
    assert poi_connection.status_code == 201, poi_connection.text

    case = await client.post(
        "/api/v1/onboarding/cases",
        headers=headers,
        json={
            "store_id": store_id,
            "category_code": "beauty_hair",
            "category_name": "美发",
            "subject_type": "individual_business",
        },
    )
    case_id = case.json()["id"]
    await client.post(
        f"/api/v1/onboarding/cases/{case_id}/precheck",
        headers=headers,
        json={"items": qualification_items(ready=True), "rule_source_reference": "rules/current"},
    )
    await client.post(
        f"/api/v1/onboarding/cases/{case_id}/official-submission",
        headers=headers,
        json={"official_reference": "filing-direct", "evidence_reference": "evidence/submitted"},
    )
    approved = await client.post(
        f"/api/v1/onboarding/cases/{case_id}/official-decision",
        headers=headers,
        json={"decision": "approved", "evidence_reference": "evidence/approved"},
    )
    assert approved.status_code == 200, approved.text

    app = await client.post(
        "/api/v1/mini-programs",
        headers=headers,
        json={
            "connection_id": commerce_connection.json()["id"],
            "name": "缔丝风尚到店服务",
            "app_id": "wx-direct-test",
            "owner_subject": "缔丝风尚美发店",
            "authorization_reference": "evidence/merchant-auth",
            "payment_merchant_id": "1900000109",
            "payment_owner_verified": True,
            "callback_configured": True,
        },
    )
    assert app.status_code == 201, app.text
    activated = await client.patch(
        f"/api/v1/mini-programs/{app.json()['id']}",
        headers=headers,
        json={
            "version": app.json()["version"],
            "status": "active",
            "location_service_status": "authorized",
        },
    )
    assert activated.status_code == 200, activated.text

    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        poi = ServicePoi(
            tenant_id=tenant_id,
            connection_id=poi_connection.json()["id"],
            external_poi_id="TX-HAIR-001",
            name="缔丝风尚美发店",
            address="河南省漯河市源汇区乐山路长江国际小区116门面房",
            remote_status="approved",
            raw_checksum="0" * 64,
        )
        session.add(poi)
        await session.commit()
        await session.refresh(poi)
        poi_id = poi.id

    mount = await client.post(
        "/api/v1/position-services",
        headers=headers,
        json={
            "onboarding_case_id": case_id,
            "store_id": store_id,
            "service_poi_id": poi_id,
            "mini_program_id": app.json()["id"],
            "service_type": "reservation",
            "service_name": "美发预约",
            "entry_path": "pages/store/index",
        },
    )
    current = mount.json()
    for target in ("service_defined", "authorization_pending", "authorized", "mounted"):
        body: dict[str, object] = {"version": current["version"], "status": target}
        if target in {"authorized", "mounted"}:
            body.update(
                {
                    "official_reference": "position-auth-001",
                    "evidence_reference": "evidence/position-approved",
                }
            )
        response = await client.post(
            f"/api/v1/position-services/{mount.json()['id']}/transition",
            headers=headers,
            json=body,
        )
        assert response.status_code == 200, response.text
        current = response.json()
    return app.json()["id"], case_id


@pytest.mark.asyncio
async def test_mock_purchase_appointment_consume_and_revoke(client: AsyncClient) -> None:
    csrf, tenant_id = await login(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    store_id = await create_store(client, csrf, tenant_id)
    mini_program_id, case_id = await ready_mini_program(client, csrf, tenant_id, store_id)
    readiness = await client.get(
        f"/api/v1/onboarding/cases/{case_id}/readiness",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert readiness.json()["ready"] is True

    product = await client.post(
        "/api/v1/direct-commerce/products",
        headers=headers,
        json={
            "mini_program_id": mini_program_id,
            "store_id": store_id,
            "merchant_product_id": "HAIR-COLOR-001",
            "name": "潮色染发套餐",
            "description": "到店使用",
            "sale_price": 9900,
            "market_price": 12900,
            "stock": 10,
            "service_minutes": 120,
        },
    )
    assert product.status_code == 201, product.text
    listed = await client.patch(
        f"/api/v1/direct-commerce/products/{product.json()['id']}",
        headers=headers,
        json={"version": product.json()["version"], "status": "listed"},
    )
    assert listed.status_code == 200, listed.text

    login_response = await client.post(
        f"/api/v1/public/mini-programs/{mini_program_id}/login",
        json={"code": "wx-login-code-one-use"},
    )
    assert login_response.status_code == 200, login_response.text
    consumer_headers = {"Authorization": "Bearer " + login_response.json()["access_token"]}
    order = await client.post(
        f"/api/v1/public/mini-programs/{mini_program_id}/orders",
        headers=consumer_headers,
        json={
            "product_id": product.json()["id"],
            "quantity": 1,
            "idempotency_key": "consumer-order-0001",
        },
    )
    assert order.status_code == 201, order.text
    paid = await client.post(
        f"/api/v1/public/mini-programs/{mini_program_id}/orders/{order.json()['id']}/pay",
        headers=consumer_headers,
        json={},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["order"]["status"] == "paid"
    voucher_code = paid.json()["mock_voucher_code"]
    assert len(voucher_code) == 12

    appointment = await client.post(
        f"/api/v1/public/mini-programs/{mini_program_id}/orders/{order.json()['id']}/appointment",
        headers=consumer_headers,
        json={
            "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "contact_name": "张女士",
            "contact_phone": "13900000000",
        },
    )
    assert appointment.status_code == 201, appointment.text
    assert appointment.json()["contact_phone_masked"] == "139****0000"

    consumed = await client.post(
        "/api/v1/direct-commerce/vouchers/consume",
        headers=headers,
        json={"code": voucher_code, "store_id": store_id},
    )
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["state"] == "consumed"
    repeated = await client.post(
        "/api/v1/direct-commerce/vouchers/consume",
        headers=headers,
        json={"code": voucher_code, "store_id": store_id},
    )
    assert repeated.status_code == 409

    revoked = await client.post(
        f"/api/v1/direct-commerce/vouchers/{consumed.json()['id']}/revoke",
        headers=headers,
        json={"version": consumed.json()["version"], "reason": "店员误核销"},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["state"] == "available"
