from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from poi_admin.connections.ports import GatewayTerminalError, GatewayTransientError
from poi_admin.connections.tokens import (
    StaticTokenProvider,
    WeChatAccessTokenProvider,
    WeChatAuthorizerTokenProvider,
    token_provider_from_secrets,
)
from poi_admin.connections.wechat_http import WeChatHttpClient


@pytest.mark.asyncio
@respx.mock
async def test_access_token_provider_fetches_caches_and_force_refreshes() -> None:
    route = respx.get("https://api.weixin.qq.com/cgi-bin/stable_token").mock(
        side_effect=[
            httpx.Response(200, json={"errcode": 0, "access_token": "first", "expires_in": 3600}),
            httpx.Response(200, json={"errcode": 0, "access_token": "second", "expires_in": 3600}),
        ]
    )
    provider = WeChatAccessTokenProvider("wx-app", "secret")

    assert await provider.get_token() == "first"
    assert await provider.get_token() == "first"
    assert await provider.get_token(force_refresh=True) == "second"
    assert route.call_count == 2
    assert route.calls[0].request.url.params["appid"] == "wx-app"
    assert route.calls[0].request.url.params["secret"] == "secret"


@pytest.mark.asyncio
@respx.mock
async def test_access_token_provider_serializes_concurrent_refreshes() -> None:
    route = respx.get("https://api.weixin.qq.com/cgi-bin/stable_token").mock(
        return_value=httpx.Response(
            200, json={"errcode": 0, "access_token": "shared", "expires_in": 3600}
        )
    )
    provider = WeChatAccessTokenProvider("wx-app", "secret")

    values = await asyncio.gather(*(provider.get_token() for _ in range(20)))

    assert values == ["shared"] * 20
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_access_token_provider_classifies_upstream_and_credential_errors() -> None:
    route = respx.get("https://api.weixin.qq.com/cgi-bin/stable_token")
    route.mock(return_value=httpx.Response(429, text="rate limited"))
    provider = WeChatAccessTokenProvider("wx-app", "secret")
    with pytest.raises(GatewayTransientError) as transient:
        await provider.get_token()
    assert transient.value.code == "token_unavailable" and transient.value.retryable

    route.mock(return_value=httpx.Response(200, json={"errcode": 40001, "errmsg": "bad app"}))
    with pytest.raises(GatewayTerminalError) as terminal:
        await provider.get_token(force_refresh=True)
    assert terminal.value.code == "token_invalid" and not terminal.value.retryable

    route.mock(return_value=httpx.Response(200, content=b"not-json"))
    with pytest.raises(GatewayTransientError) as malformed:
        await provider.get_token(force_refresh=True)
    assert malformed.value.code == "invalid_upstream_response"


@pytest.mark.asyncio
@respx.mock
async def test_access_token_provider_handles_timeout_and_invalid_token_shape() -> None:
    route = respx.get("https://api.weixin.qq.com/cgi-bin/stable_token").mock(
        side_effect=httpx.ReadTimeout("token timeout")
    )
    provider = WeChatAccessTokenProvider("wx-app", "secret")
    with pytest.raises(GatewayTransientError, match="unavailable"):
        await provider.get_token()

    route.mock(return_value=httpx.Response(200, json={"errcode": 0, "expires_in": 3600}))
    with pytest.raises(GatewayTransientError) as missing:
        await provider.get_token(force_refresh=True)
    assert missing.value.code == "invalid_upstream_response"


def test_token_provider_factory_prefers_static_token_and_requires_live_credentials() -> None:
    static = token_provider_from_secrets("wx-app", {"access_token": "already"})
    assert isinstance(static, StaticTokenProvider)

    with pytest.raises(GatewayTerminalError) as missing:
        token_provider_from_secrets(None, {})
    assert missing.value.code == "credentials_missing"


@pytest.mark.asyncio
@respx.mock
async def test_authorizer_token_provider_refreshes_component_authorization() -> None:
    route = respx.post(
        "https://api.weixin.qq.com/cgi-bin/component/api_authorizer_token"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "authorizer_access_token": "authorizer-new",
                "authorizer_refresh_token": "refresh-new",
                "expires_in": 3600,
            },
        )
    )
    provider = token_provider_from_secrets(
        "wx-authorizer",
        {
            "authorizer_refresh_token": "refresh-old",
            "component_app_id": "wx-component",
            "component_access_token": "component-token",
        },
    )

    assert isinstance(provider, WeChatAuthorizerTokenProvider)
    assert await provider.get_token() == "authorizer-new"
    assert await provider.get_token() == "authorizer-new"
    assert route.call_count == 1
    assert route.calls[0].request.url.params["component_access_token"] == "component-token"
    assert json.loads(route.calls[0].request.content) == {
        "component_appid": "wx-component",
        "authorizer_appid": "wx-authorizer",
        "authorizer_refresh_token": "refresh-old",
    }


class RecordingTokenProvider:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def get_token(self, *, force_refresh: bool = False) -> str:
        self.calls.append(force_refresh)
        return "fresh" if force_refresh else "stale"


@pytest.mark.asyncio
@respx.mock
async def test_wechat_http_refreshes_once_after_token_error() -> None:
    responses = [
        httpx.Response(200, json={"errcode": 40001, "errmsg": "expired"}),
        httpx.Response(200, json={"errcode": 0, "data": {"ok": True}}),
    ]
    route = respx.post("https://api.weixin.qq.com/test").mock(side_effect=responses)
    provider = RecordingTokenProvider()
    client = WeChatHttpClient(provider)

    result = await client.post_json("/test", {"name": "demo"})

    assert result == {"errcode": 0, "data": {"ok": True}}
    assert route.call_count == 2
    assert provider.calls == [False, True]
    assert route.calls[0].request.url.params["access_token"] == "stale"
    assert route.calls[1].request.url.params["access_token"] == "fresh"


@pytest.mark.asyncio
@respx.mock
async def test_wechat_http_classifies_http_and_wechat_errors() -> None:
    route = respx.post("https://api.weixin.qq.com/test")
    client = WeChatHttpClient(StaticTokenProvider("token"))

    route.mock(return_value=httpx.Response(429, text="rate limit"))
    with pytest.raises(GatewayTransientError) as rate:
        await client.post_json("/test")
    assert rate.value.code == "upstream_unavailable"

    route.mock(return_value=httpx.Response(400, text="bad request"))
    with pytest.raises(GatewayTerminalError) as bad_request:
        await client.post_json("/test")
    assert bad_request.value.code == "http_400"

    route.mock(return_value=httpx.Response(200, json={"errcode": 45009, "errmsg": "busy"}))
    with pytest.raises(GatewayTransientError) as busy:
        await client.post_json("/test")
    assert busy.value.code == "wechat_45009"

    route.mock(return_value=httpx.Response(200, json={"errcode": 40003, "errmsg": "invalid"}))
    with pytest.raises(GatewayTerminalError) as invalid:
        await client.post_json("/test")
    assert invalid.value.code == "wechat_40003"


@pytest.mark.asyncio
@respx.mock
async def test_wechat_http_handles_timeout_malformed_non_object_and_oversized_responses() -> None:
    route = respx.post("https://api.weixin.qq.com/test")
    client = WeChatHttpClient(StaticTokenProvider("token"), max_response_bytes=8)

    route.mock(side_effect=httpx.ReadTimeout("request timeout"))
    with pytest.raises(GatewayTransientError) as timeout:
        await client.post_json("/test")
    assert timeout.value.code == "upstream_unavailable"

    route.mock(return_value=httpx.Response(200, content=b"not-json"))
    with pytest.raises(GatewayTransientError) as malformed:
        await client.post_json("/test")
    assert malformed.value.code == "invalid_upstream_response"

    route.mock(return_value=httpx.Response(200, json=["x"]))
    client = WeChatHttpClient(StaticTokenProvider("token"), max_response_bytes=1024)
    with pytest.raises(GatewayTransientError) as non_object:
        await client.post_json("/test")
    assert non_object.value.code == "invalid_upstream_response"

    client = WeChatHttpClient(StaticTokenProvider("token"), max_response_bytes=8)
    route.mock(return_value=httpx.Response(200, content=b"123456789"))
    with pytest.raises(GatewayTerminalError) as oversized:
        await client.post_json("/test")
    assert oversized.value.code == "response_too_large"
