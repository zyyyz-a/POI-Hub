from __future__ import annotations

import pytest
from httpx import AsyncClient


async def login(client: AsyncClient) -> tuple[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200
    csrf = response.cookies["poi_csrf"]
    tenants = response.json()["tenants"]
    if tenants:
        tenant_id = tenants[0]["tenant_id"]
    else:
        created = await client.post(
            "/api/v1/platform/tenants",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Onboarding Test", "slug": "onboarding-test"},
        )
        assert created.status_code == 201
        tenant_id = created.json()["id"]
    return csrf, tenant_id


async def create_store(client: AsyncClient, csrf: str, tenant_id: str) -> str:
    response = await client.post(
        "/api/v1/stores",
        headers={"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id},
        json={
            "code": "HAIR-001",
            "name": "缔丝风尚潮色染烫",
            "address": "河南省漯河市源汇区乐山路长江国际小区116门面房",
            "city": "漯河市",
            "district": "源汇区",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def qualification_items(*, ready: bool) -> list[dict[str, object]]:
    return [
        {
            "code": code,
            "label": code,
            "required": True,
            "present": ready,
            "verified": ready,
            "evidence_reference": f"evidence/{code}" if ready else None,
        }
        for code in (
            "official_category_open",
            "region_supported",
            "business_license",
            "merchant_admin_confirmed",
            "storefront_photo",
            "interior_photo",
            "public_phone",
            "map_location",
            "settlement_account",
        )
    ]


@pytest.mark.asyncio
async def test_precheck_blocks_then_allows_official_submission(client: AsyncClient) -> None:
    csrf, tenant_id = await login(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    store_id = await create_store(client, csrf, tenant_id)
    created = await client.post(
        "/api/v1/onboarding/cases",
        headers=headers,
        json={
            "store_id": store_id,
            "category_code": "beauty_hair",
            "category_name": "美发",
            "subject_type": "individual_business",
            "region_code": "411102",
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    failed = await client.post(
        f"/api/v1/onboarding/cases/{case_id}/precheck",
        headers=headers,
        json={
            "items": qualification_items(ready=False),
            "rule_source_reference": "wechat-support/2026-08-30",
        },
    )
    assert failed.status_code == 200
    assert failed.json()["precheck_status"] == "failed"
    rejected_submission = await client.post(
        f"/api/v1/onboarding/cases/{case_id}/official-submission",
        headers=headers,
        json={"official_reference": "filing-1", "evidence_reference": "evidence/filing-1"},
    )
    assert rejected_submission.status_code == 422
    assert rejected_submission.json()["detail"]["code"] == "precheck_required"

    passed = await client.post(
        f"/api/v1/onboarding/cases/{case_id}/precheck",
        headers=headers,
        json={
            "items": qualification_items(ready=True),
            "rule_source_reference": "verified-channel/category-rules-2026-08-30",
        },
    )
    assert passed.status_code == 200
    assert passed.json()["precheck_status"] == "passed"
    submitted = await client.post(
        f"/api/v1/onboarding/cases/{case_id}/official-submission",
        headers=headers,
        json={"official_reference": "filing-1", "evidence_reference": "evidence/filing-1"},
    )
    assert submitted.status_code == 200
    assert submitted.json()["official_status"] == "under_review"


@pytest.mark.asyncio
async def test_official_approval_and_position_mount_require_evidence(client: AsyncClient) -> None:
    csrf, tenant_id = await login(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    store_id = await create_store(client, csrf, tenant_id)
    created = await client.post(
        "/api/v1/onboarding/cases",
        headers=headers,
        json={
            "store_id": store_id,
            "category_code": "beauty_hair",
            "category_name": "美发",
            "subject_type": "individual_business",
        },
    )
    case_id = created.json()["id"]
    await client.post(
        f"/api/v1/onboarding/cases/{case_id}/precheck",
        headers=headers,
        json={
            "items": qualification_items(ready=True),
            "rule_source_reference": "rules/current",
        },
    )
    await client.post(
        f"/api/v1/onboarding/cases/{case_id}/official-submission",
        headers=headers,
        json={"official_reference": "filing-2", "evidence_reference": "evidence/submitted"},
    )
    approved = await client.post(
        f"/api/v1/onboarding/cases/{case_id}/official-decision",
        headers=headers,
        json={"decision": "approved", "evidence_reference": "evidence/official-approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["official_status"] == "approved"

    app = await client.post(
        "/api/v1/mini-programs",
        headers=headers,
        json={
            "name": "缔丝风尚到店服务",
            "app_id": "wx-hair-mini",
            "owner_subject": "缔丝风尚美发店",
            "authorization_reference": "auth/merchant-scan",
            "payment_merchant_id": "1749846048",
            "payment_owner_verified": True,
            "callback_configured": True,
        },
    )
    assert app.status_code == 201
    app_id = app.json()["id"]
    app_updated = await client.patch(
        f"/api/v1/mini-programs/{app_id}",
        headers=headers,
        json={
            "version": app.json()["version"],
            "status": "authorized",
            "location_service_status": "authorized",
        },
    )
    assert app_updated.status_code == 200

    mount = await client.post(
        "/api/v1/position-services",
        headers=headers,
        json={
            "onboarding_case_id": case_id,
            "store_id": store_id,
            "mini_program_id": app_id,
            "service_type": "group_buying",
            "service_name": "到店团购",
            "entry_path": "pages/store/index",
        },
    )
    assert mount.status_code == 201
    mount_id = mount.json()["id"]
    defined = await client.post(
        f"/api/v1/position-services/{mount_id}/transition",
        headers=headers,
        json={"version": mount.json()["version"], "status": "service_defined"},
    )
    pending = await client.post(
        f"/api/v1/position-services/{mount_id}/transition",
        headers=headers,
        json={"version": defined.json()["version"], "status": "authorization_pending"},
    )
    missing_evidence = await client.post(
        f"/api/v1/position-services/{mount_id}/transition",
        headers=headers,
        json={"version": pending.json()["version"], "status": "authorized"},
    )
    assert missing_evidence.status_code == 422
    assert missing_evidence.json()["detail"]["code"] == "position_evidence_required"

    readiness = await client.get(
        f"/api/v1/onboarding/cases/{case_id}/readiness",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is False
    assert "微信位置服务尚未挂载" in readiness.json()["blockers"]
