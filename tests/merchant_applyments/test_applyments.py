from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import httpx
import pytest
import pytest_asyncio
import respx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import select
from tests.onboarding.test_onboarding_routes import create_store, login

from poi_admin.audit.models import AuditLog
from poi_admin.core.dependencies import get_auth_context
from poi_admin.core.permissions import Role
from poi_admin.direct_commerce.wechat_pay import rsa_sign
from poi_admin.merchant_applyments.contracts import REQUIRED_ATTACHMENTS
from poi_admin.merchant_applyments.gateway import API_HOST, APPLYMENT_PATH, MEDIA_PATH
from poi_admin.merchant_applyments.limits import MAX_IMAGE_BYTES
from poi_admin.merchant_applyments.models import ApplymentAttachment, MerchantApplyment, utcnow
from poi_admin.merchant_applyments.service import safe_sign_url

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aPVcAAAAASUVORK5CYII="
)
FIELDS = {
    "merchant_name": "个体户测试经营者",
    "license_number": "123456789012345",
    "owner_name": "测试经营者",
    "id_number": "11010519491231002X",
    "id_period_begin": "2020-01-01",
    "id_period_end": "长期",
    "mobile_phone": "13800138000",
    "contact_email": "proprietor@example.com",
    "merchant_shortname": "试点门店",
    "service_phone": "03951234567",
    "store_name": "试点门店",
    "store_address": "测试经营地址",
    "store_area_code": "411102",
    "bank_account_type": "personal",
    "account_bank": "工商银行",
    "bank_name": "测试支行",
    "account_number": "6222000000001234567",
    "settlement_id": "719",
    "qualification_type": "测试行业（非真实提交）",
    "settlement_rule_confirmed": True,
}


@pytest.fixture(scope="module")
def keys():
    merchant = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wechat = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def private_pem(key):
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

    bundle = {
        "merchant_private_key_pem": private_pem(merchant),
        "merchant_serial_no": "TESTSERIAL",
        "wechatpay_public_key_pem": wechat.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
        "wechatpay_public_key_id": "PUB_KEY_ID_TEST_ONLY",
    }
    return bundle, wechat, private_pem(wechat)


def signed(keys, body, status=200):
    text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    return httpx.Response(
        status,
        content=text.encode(),
        headers={
            "Content-Type": "application/json",
            "Wechatpay-Serial": "PUB_KEY_ID_TEST_ONLY",
            "Wechatpay-Timestamp": timestamp,
            "Wechatpay-Nonce": "test-response-nonce",
            "Wechatpay-Signature": rsa_sign(
                timestamp + "\ntest-response-nonce\n" + text + "\n", keys[2]
            ),
            "Request-ID": "test-provider-request-id",
        },
    )


@pytest_asyncio.fixture
async def draft(client, keys):
    csrf, tenant_id = await login(client)
    headers = {"X-CSRF-Token": csrf, "X-Tenant-ID": tenant_id}
    store_id = await create_store(client, csrf, tenant_id)
    connection = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={
            "capability": "mini_program_commerce",
            "mode": "live",
            "app_id": "wx618a9c524fc951ed",
            "merchant_id": "1118323241",
            "secrets": keys[0],
        },
    )
    assert connection.status_code == 201, connection.text
    result = await client.post(
        "/api/v1/merchant-applyments",
        headers=headers,
        json={
            "store_id": store_id,
            "connection_id": connection.json()["id"],
        },
    )
    assert result.status_code == 201, result.text
    return headers, result.json()


async def complete(client, headers, row):
    path = "/api/v1/merchant-applyments/" + row["id"]
    response = await client.put(
        path, headers=headers, json={"version": row["version"], "fields": FIELDS}
    )
    assert response.status_code == 200, response.text
    row = response.json()
    for kind in REQUIRED_ATTACHMENTS:
        response = await client.post(
            path + f"/attachments/{kind}?version={row['version']}", headers=headers, content=PNG
        )
        assert response.status_code == 200, response.text
        row = response.json()
    assert row["issues"] == []
    return row


def enable(client):
    app = client._transport.app
    app.state.settings = app.state.settings.model_copy(
        update={"wechat_applyment_submit_enabled": True}
    )


async def test_draft_and_attachments_are_encrypted_not_sent_or_listed(client, draft):
    headers, row = draft
    with respx.mock(assert_all_called=False) as remote:
        row = await complete(client, headers, row)
        assert len(remote.calls) == 0
    result = await client.get("/api/v1/merchant-applyments", headers=headers)
    assert result.headers["Cache-Control"] == "no-store, private"
    for value in (FIELDS["id_number"], FIELDS["account_number"], FIELDS["owner_name"]):
        assert value not in result.text
    assert result.json()[0]["fields"] is None
    async with client._transport.app.state.database.session_factory() as session:
        stored = await session.get(MerchantApplyment, row["id"])
        assert FIELDS["id_number"] not in stored.encrypted_fields
        assert FIELDS["account_number"] not in stored.encrypted_fields
        image = await session.scalar(select(ApplymentAttachment))
        assert base64.b64encode(PNG).decode() not in image.encrypted_content
        logs = (await session.scalars(select(AuditLog))).all()
        serialized = str([(log.before_summary, log.after_summary) for log in logs])
        assert FIELDS["id_number"] not in serialized
    # List/detail inspection cannot create an upstream application.
    assert row["state"] == "draft" and row["applyment_id"] is None


async def test_submission_requires_server_gate_explicit_consent_and_complete_data(client, draft):
    headers, row = draft
    path = "/api/v1/merchant-applyments/" + row["id"] + "/submit"
    consent = {
        "version": row["version"],
        "merchant_authorized": True,
        "confirm_real_submission": True,
    }
    assert (await client.post(path, headers=headers, json=consent)).status_code == 403
    enable(client)
    assert (
        await client.post(path, headers=headers, json={"version": row["version"]})
    ).status_code == 422
    assert (await client.post(path, headers=headers, json=consent)).status_code == 422


async def test_real_request_shape_encryption_progress_and_payment_draft(client, draft, keys):
    headers, row = draft
    row = await complete(client, headers, row)
    enable(client)
    path = "/api/v1/merchant-applyments/" + row["id"]
    with respx.mock as remote:
        media = remote.post(API_HOST + MEDIA_PATH).mock(
            side_effect=lambda request: signed(keys, {"media_id": "media-test-only"})
        )
        submitted = remote.post(API_HOST + APPLYMENT_PATH).mock(
            return_value=signed(keys, {"applyment_id": 200000000001})
        )
        response = await client.post(
            path + "/submit",
            headers=headers,
            json={
                "version": row["version"],
                "merchant_authorized": True,
                "confirm_real_submission": True,
            },
        )
        assert response.status_code == 200, response.text
        row = response.json()
        assert row["state"] == "reviewing"
        assert media.call_count == len(REQUIRED_ATTACHMENTS)
        upload_request = media.calls[0].request
        multipart = BytesParser(policy=policy.default).parsebytes(
            ("Content-Type: " + upload_request.headers["Content-Type"] + "\r\n\r\n").encode()
            + upload_request.content
        )
        meta_body = list(multipart.iter_parts())[0].get_payload(decode=True)
        assert json.loads(meta_body)["sha256"] == hashlib.sha256(PNG).hexdigest()
        auth = dict(re.findall(r'(\w+)="([^"]*)"', upload_request.headers["Authorization"]))
        canonical = (
            f"POST\n{MEDIA_PATH}\n{auth['timestamp']}\n{auth['nonce_str']}\n"
            + meta_body.decode()
            + "\n"
        )
        merchant_key = serialization.load_pem_private_key(
            keys[0]["merchant_private_key_pem"].encode(), password=None
        )
        merchant_key.public_key().verify(
            base64.b64decode(auth["signature"]),
            canonical.encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        payload = json.loads(submitted.calls[0].request.content)
        assert payload["subject_info"]["subject_type"] == "SUBJECT_TYPE_INDIVIDUAL"
        assert payload["contact_info"]["contact_type"] == "LEGAL"
        assert (
            payload["business_info"]["sales_info"]["mini_program_info"]["mini_program_appid"]
            == "wx618a9c524fc951ed"
        )
        encrypted_id = payload["subject_info"]["identity_info"]["id_card_info"]["id_card_number"]
        assert (
            keys[1]
            .decrypt(
                base64.b64decode(encrypted_id),
                padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
            )
            .decode()
            == FIELDS["id_number"]
        )
        assert FIELDS["id_number"] not in submitted.calls[0].request.content.decode()
        assert (
            await client.post(
                path + "/link-payment", headers=headers, json={"version": row["version"]}
            )
        ).status_code == 409
        query = remote.get(API_HOST + APPLYMENT_PATH + "business_code/" + row["business_code"])
        query.mock(
            return_value=signed(
                keys,
                {
                    "applyment_id": 200000000001,
                    "applyment_state": "APPLYMENT_STATE_TO_BE_SIGNED",
                    "sign_url": "https://pay.weixin.qq.com/apply/confirm?id=test-only",
                },
            )
        )
        response = await client.post(
            path + "/sync", headers=headers, json={"version": row["version"]}
        )
        row = response.json()
        assert row["state"] == "needs_signature" and row["sign_url"].startswith(
            "https://pay.weixin.qq.com/"
        )
        query.mock(
            return_value=signed(
                keys,
                {
                    "applyment_id": 200000000001,
                    "applyment_state": "APPLYMENT_STATE_FINISHED",
                    "sub_mchid": "1900000009",
                },
            )
        )
        row = (
            await client.post(path + "/sync", headers=headers, json={"version": row["version"]})
        ).json()
        assert row["state"] == "finished"
        linked = await client.post(
            path + "/link-payment", headers=headers, json={"version": row["version"]}
        )
        assert linked.status_code == 200, linked.text
    profile = (
        await client.get("/api/v1/direct-commerce/payment-profiles", headers=headers)
    ).json()[0]
    assert profile["mode"] == "partner" and profile["sub_mchid"] == "1900000009"
    assert profile["verified"] is True and profile["status"] == "draft"


@pytest.mark.parametrize("failure", ["timeout", "bad_signature", "permission"])
async def test_uncertain_submission_is_locked_and_no_auth_is_not_success(
    client, draft, keys, failure
):
    headers, row = draft
    row = await complete(client, headers, row)
    enable(client)
    path = "/api/v1/merchant-applyments/" + row["id"]
    with respx.mock as remote:
        remote.post(API_HOST + MEDIA_PATH).mock(
            side_effect=lambda request: signed(keys, {"media_id": "test-media"})
        )
        submit = remote.post(API_HOST + APPLYMENT_PATH)
        if failure == "timeout":
            submit.mock(side_effect=httpx.ReadTimeout("test timeout"))
        elif failure == "bad_signature":
            submit.mock(return_value=httpx.Response(200, json={"applyment_id": 123}))
        else:
            submit.mock(
                return_value=signed(keys, {"code": "NO_AUTH", "message": FIELDS["id_number"]}, 403)
            )
        row = (
            await client.post(
                path + "/submit",
                headers=headers,
                json={
                    "version": row["version"],
                    "merchant_authorized": True,
                    "confirm_real_submission": True,
                },
            )
        ).json()
        expected = "draft" if failure == "permission" else "submission_unknown"
        assert row["state"] == expected
        assert row["sub_mchid"] is None
        if failure == "permission":
            assert row["last_error_code"] == "NO_AUTH"
        else:
            assert (
                await client.post(
                    path + "/submit",
                    headers=headers,
                    json={
                        "version": row["version"],
                        "merchant_authorized": True,
                        "confirm_real_submission": True,
                    },
                )
            ).status_code == 409
        assert submit.call_count == 1


async def test_tenant_csrf_roles_validation_and_stale_versions(client, draft):
    headers, row = draft
    path = "/api/v1/merchant-applyments/" + row["id"]
    no_csrf = await client.put(
        path, headers={"X-Tenant-ID": headers["X-Tenant-ID"]}, json={"version": 1, "fields": {}}
    )
    assert no_csrf.status_code == 403
    created = await client.post(
        "/api/v1/platform/tenants",
        headers=headers,
        json={"name": "Other applyment tenant", "slug": "other-applyment"},
    )
    assert created.status_code == 201
    assert (
        await client.get(path, headers={**headers, "X-Tenant-ID": created.json()["id"]})
    ).status_code == 404
    invalid = await client.put(
        path, headers=headers, json={"version": 1, "fields": {"id_number": FIELDS["id_number"] * 4}}
    )
    assert invalid.status_code == 422 and FIELDS["id_number"] not in invalid.text
    good = await client.put(path, headers=headers, json={"version": 1, "fields": FIELDS})
    assert good.status_code == 200
    stale = await client.put(path, headers=headers, json={"version": 1, "fields": {}})
    assert stale.status_code == 409
    # Dependency override uses a fixed captured real context, not new authentication machinery.
    app = client._transport.app
    from poi_admin.core.dependencies import AuthContext
    from poi_admin.identity.models import Tenant, User, UserSession

    async with app.state.database.session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "admin@example.com"))
        auth_session = await session.scalar(
            select(UserSession).where(UserSession.user_id == user.id)
        )
        tenant = await session.get(Tenant, headers["X-Tenant-ID"])
        context = AuthContext(user, auth_session, tenant, None, Role.OPERATOR)

    async def fixed_operator():
        return context

    app.dependency_overrides[get_auth_context] = fixed_operator
    try:
        assert (await client.get(path, headers=headers)).status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_attachment_size_type_and_completed_record_cannot_be_forged(client, draft):
    headers, row = draft
    path = "/api/v1/merchant-applyments/" + row["id"]
    invalid = await client.post(
        path + "/attachments/license?version=1",
        headers=headers,
        content=b"<svg>not a private photo</svg>",
    )
    assert invalid.status_code == 422
    oversized = await client.post(
        path + "/attachments/license?version=1",
        headers=headers,
        content=b"x" * (MAX_IMAGE_BYTES + 1),
    )
    assert oversized.status_code == 413
    forged = await client.put(
        path,
        headers=headers,
        json={"version": 1, "fields": {}, "state": "finished", "sub_mchid": "1900000009"},
    )
    assert forged.status_code == 422
    assert (await client.get(path, headers=headers)).json()["version"] == 1


async def test_photo_above_old_limit_and_new_exact_boundary_are_accepted(client, draft):
    headers, row = draft
    path = "/api/v1/merchant-applyments/" + row["id"]
    capabilities = await client.get("/api/v1/merchant-applyments/capabilities", headers=headers)
    assert capabilities.json()["max_image_bytes"] == MAX_IMAGE_BYTES == 5 * 1024 * 1024
    for size in (3 * 1024 * 1024, MAX_IMAGE_BYTES):
        photo = PNG + b"\0" * (size - len(PNG))
        response = await client.post(
            path + f"/attachments/license?version={row['version']}", headers=headers, content=photo
        )
        assert response.status_code == 200, response.text
        row = response.json()
        assert row["attachments"][0]["size_bytes"] == size
        assert row["state"] == "draft" and row["applyment_id"] is None


def test_only_official_sign_links_are_rendered():
    assert safe_sign_url("https://pay.weixin.qq.com/apply?id=x")
    for value in (
        "javascript:alert(1)",
        "https://pay.weixin.qq.com.evil.example/x",
        "https://attacker@evil.example/x",
        "https://pay.weixin.qq.com:444/x",
    ):
        assert safe_sign_url(value) is None


@pytest.mark.parametrize("mismatch", ["business_code", "applyment_id", "sub_mchid"])
async def test_signed_query_cannot_link_another_application_or_replace_submerchant(
    client, draft, keys, mismatch
):
    headers, row = draft
    async with client._transport.app.state.database.session_factory() as session:
        stored = await session.get(MerchantApplyment, row["id"])
        stored.state = "finished" if mismatch == "sub_mchid" else "reviewing"
        stored.applyment_id = "200000000001"
        stored.submitted_at = utcnow() - timedelta(minutes=10)
        if mismatch == "sub_mchid":
            stored.sub_mchid = "1900000009"
        await session.commit()
    result = {
        "business_code": row["business_code"],
        "applyment_id": "200000000001",
        "applyment_state": "APPLYMENT_STATE_FINISHED",
        "sub_mchid": "1900000009",
    }
    result[mismatch] = "different" if mismatch == "business_code" else "9999999999"
    path = "/api/v1/merchant-applyments/" + row["id"]
    with respx.mock as remote:
        remote.get(API_HOST + APPLYMENT_PATH + "business_code/" + row["business_code"]).mock(
            return_value=signed(keys, result)
        )
        response = await client.post(
            path + "/sync", headers=headers, json={"version": row["version"]}
        )
        assert response.status_code == 409, response.text
    current = (await client.get(path, headers=headers)).json()
    assert current["applyment_id"] == "200000000001"
    assert current["sub_mchid"] != "9999999999"
    assert current["version"] == row["version"]


async def test_unknown_submission_recovery_uses_submission_time_not_last_poll(client, draft, keys):
    headers, row = draft
    async with client._transport.app.state.database.session_factory() as session:
        stored = await session.get(MerchantApplyment, row["id"])
        stored.state = "submission_unknown"
        stored.submitted_at = utcnow() - timedelta(seconds=301)
        stored.updated_at = utcnow()  # Repeated polling must not postpone recovery forever.
        await session.commit()
    with respx.mock as remote:
        remote.get(API_HOST + APPLYMENT_PATH + "business_code/" + row["business_code"]).mock(
            return_value=signed(keys, {"code": "PARAM_ERROR", "message": "未能找到申请单"}, 400)
        )
        response = await client.post(
            "/api/v1/merchant-applyments/" + row["id"] + "/sync",
            headers=headers,
            json={"version": row["version"]},
        )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "draft"
    assert response.json()["business_code"] == row["business_code"]


async def test_active_submission_has_lease_and_changed_appid_is_rejected(client, draft):
    headers, row = draft
    path = "/api/v1/merchant-applyments/" + row["id"]
    async with client._transport.app.state.database.session_factory() as session:
        stored = await session.get(MerchantApplyment, row["id"])
        stored.state = "submitting"
        stored.submitted_at = utcnow()
        await session.commit()
    with respx.mock(assert_all_called=False) as remote:
        response = await client.post(
            path + "/sync", headers=headers, json={"version": row["version"]}
        )
        assert response.status_code == 409
        assert not remote.calls
    async with client._transport.app.state.database.session_factory() as session:
        from poi_admin.connections.models import WeChatConnection

        stored = await session.get(MerchantApplyment, row["id"])
        stored.state = "reviewing"
        connection = await session.get(WeChatConnection, row["connection_id"])
        connection.app_id = "wx0000000000000000"
        await session.commit()
    with respx.mock(assert_all_called=False) as remote:
        response = await client.post(
            path + "/sync", headers=headers, json={"version": row["version"]}
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "platform_appid_changed"
        assert not remote.calls
