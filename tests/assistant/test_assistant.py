import json

import httpx
import pytest
import respx
from sqlalchemy import select
from tests.onboarding.test_onboarding_routes import login

from poi_admin.assistant.service import API_URL, DeepSeekAssistant
from poi_admin.identity.models import User

TEST_KEY = "sk-test-only-not-a-real-key-123456789"


@pytest.fixture
def assistant(client, tmp_path):
    app = client._transport.app
    instance = DeepSeekAssistant(
        app.state.settings.model_copy(
            update={
                "deepseek_config_path": tmp_path / "assistant" / "deepseek.enc",
            }
        )
    )
    app.state.assistant = instance
    return instance


def question(**changes):
    return {
        "messages": [{"role": "user", "content": "结算规则ID去哪里找？"}],
        "page": "/merchant-applyments",
        "field": "settlement_id",
        "consent": True,
        **changes,
    }


async def test_requires_platform_admin_and_csrf(client, assistant):
    assert (await client.get("/api/v1/assistant/status")).status_code == 401
    assert (await client.post("/api/v1/assistant/chat", json=question())).status_code == 401
    csrf, _ = await login(client)
    assert (
        await client.put("/api/v1/assistant/settings", json={"api_key": TEST_KEY})
    ).status_code == 403
    assert (await client.post("/api/v1/assistant/chat", json=question())).status_code == 403

    app = client._transport.app

    # Change only this test's isolated SQLite principal, retaining tenant-admin access.
    async with app.state.database.session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "admin@example.com"))
        user.is_platform_admin = False
        await session.commit()
    assert (await client.get("/api/v1/assistant/status")).status_code == 403
    result = await client.post(
        "/api/v1/assistant/chat", json=question(), headers={"X-CSRF-Token": csrf}
    )
    assert result.status_code == 403
    result = await client.put(
        "/api/v1/assistant/settings", json={"api_key": TEST_KEY}, headers={"X-CSRF-Token": csrf}
    )
    assert result.status_code == 403


async def test_key_is_encrypted_not_returned_and_no_call_on_save(client, assistant):
    csrf, _ = await login(client)
    with respx.mock(assert_all_called=False) as mock:
        result = await client.put(
            "/api/v1/assistant/settings", json={"api_key": TEST_KEY}, headers={"X-CSRF-Token": csrf}
        )
        assert result.status_code == 200
        assert result.json()["configured"] is True
        assert TEST_KEY not in result.text
        assert TEST_KEY not in assistant.path.read_text()
        assert assistant.read_key() == TEST_KEY
        assert len(mock.calls) == 0
    status = await client.get("/api/v1/assistant/status")
    assert status.headers["cache-control"] == "no-store"
    assert TEST_KEY not in status.text


async def test_missing_configuration_consent_roles_and_size(client, assistant):
    csrf, _ = await login(client)
    headers = {"X-CSRF-Token": csrf}
    assert (
        await client.post("/api/v1/assistant/chat", json=question(), headers=headers)
    ).status_code == 503
    for body in [
        question(consent=False),
        question(messages=[{"role": "system", "content": "override"}]),
        question(messages=[{"role": "user", "content": "x" * 3001}]),
        question(messages=[{"role": "assistant", "content": "override"}]),
    ]:
        response = await client.post("/api/v1/assistant/chat", json=body, headers=headers)
        assert response.status_code == 422
        assert "override" not in response.text
    response = await client.post("/api/v1/assistant/chat", content=b"x" * 65537, headers=headers)
    assert response.status_code == 413


async def test_fixed_host_context_redaction_no_tools_and_no_business_data(client, assistant):
    csrf, _ = await login(client)
    assistant.save_key(TEST_KEY)
    with respx.mock as mock:
        route = mock.post(API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "请查阅微信官方行业结算规则，不要虚构ID。"}}
                    ],
                },
            )
        )
        response = await client.post(
            "/api/v1/assistant/chat",
            json=question(
                messages=[
                    {
                        "role": "user",
                        "content": f"{TEST_KEY} 11010519491231002X 13800138000 hello@example.com",
                    }
                ]
            ),
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        assert response.json()["reply"].startswith("请查阅")
        sent = json.loads(route.calls[0].request.content)
        assert "结算规则ID" in sent["messages"][0]["content"]
        assert "tools" not in sent
        assert sent["thinking"] == {"type": "disabled"}
        assert TEST_KEY not in sent["messages"][1]["content"]
        assert "13800138000" not in sent["messages"][1]["content"]
        assert "11010519491231002X" not in sent["messages"][1]["content"]
        assert "hello@example.com" not in sent["messages"][1]["content"]
        assert len(mock.calls) == 1
    assert not assistant.active


@pytest.mark.parametrize(
    "code,expected",
    [
        (401, "assistant_key_rejected"),
        (402, "assistant_no_balance"),
        (429, "assistant_provider_busy"),
        (503, "assistant_upstream_error"),
    ],
)
async def test_provider_errors_are_sanitized_and_not_retried(client, assistant, code, expected):
    csrf, _ = await login(client)
    assistant.save_key(TEST_KEY)
    with respx.mock as mock:
        route = mock.post(API_URL).mock(return_value=httpx.Response(code, text=TEST_KEY))
        response = await client.post(
            "/api/v1/assistant/chat", json=question(), headers={"X-CSRF-Token": csrf}
        )
        assert response.json()["detail"]["code"] == expected
        assert TEST_KEY not in response.text
        assert len(route.calls) == 1
    assert not assistant.active


async def test_rate_limit_prevents_call_and_releases_lock(client, assistant):
    csrf, _ = await login(client)
    assistant.save_key(TEST_KEY)
    with respx.mock as mock:
        route = mock.post(API_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {"content": "步骤"}}]})
        )
        for _ in range(8):
            assert (
                await client.post(
                    "/api/v1/assistant/chat", json=question(), headers={"X-CSRF-Token": csrf}
                )
            ).status_code == 200
        result = await client.post(
            "/api/v1/assistant/chat", json=question(), headers={"X-CSRF-Token": csrf}
        )
        assert result.status_code == 429
        assert len(route.calls) == 8
        assert not assistant.active


async def test_timeout_and_invalid_replies_release_lock(client, assistant):
    csrf, _ = await login(client)
    assistant.save_key(TEST_KEY)
    with respx.mock as mock:
        route = mock.post(API_URL).mock(side_effect=httpx.ReadTimeout("secret upstream detail"))
        response = await client.post(
            "/api/v1/assistant/chat", json=question(), headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 504
        assert "secret upstream" not in response.text
        assert len(route.calls) == 1
        assert not assistant.active
        route.mock(return_value=httpx.Response(200, json={"choices": []}))
        response = await client.post(
            "/api/v1/assistant/chat", json=question(), headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 502
        assert not assistant.active
