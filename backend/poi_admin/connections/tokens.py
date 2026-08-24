"""Access-token providers for server-side WeChat API calls."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .ports import GatewayTerminalError, GatewayTransientError


class AccessTokenProvider(Protocol):
    async def get_token(self, *, force_refresh: bool = False) -> str: ...


@dataclass(slots=True)
class StaticTokenProvider:
    """A deterministic token provider used by tests and local adapters."""

    token: str

    async def get_token(self, *, force_refresh: bool = False) -> str:
        del force_refresh
        if not self.token:
            raise GatewayTerminalError("access token is not configured", code="token_missing")
        return self.token


class WeChatAccessTokenProvider:
    """Refresh and cache an app access token with one lock per provider."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        initial_token: str | None = None,
        expires_at: float | None = None,
        base_url: str = "https://api.weixin.qq.com",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self._client = http_client
        self._token = initial_token
        self._expires_at = expires_at or 0.0
        self._lock = asyncio.Lock()

    async def get_token(self, *, force_refresh: bool = False) -> str:
        now = time.time()
        if not force_refresh and self._token and self._expires_at - now > 60:
            return self._token
        async with self._lock:
            now = time.time()
            if not force_refresh and self._token and self._expires_at - now > 60:
                return self._token
            return await self._refresh()

    async def _refresh(self) -> str:
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        f"{self.base_url}/cgi-bin/stable_token", params=params
                    )
            else:
                response = await self._client.get(
                    f"{self.base_url}/cgi-bin/stable_token", params=params
                )
        except (httpx.TimeoutException, httpx.NetworkError, OSError) as error:
            raise GatewayTransientError(
                "WeChat token service unavailable", code="token_unavailable"
            ) from error
        if response.status_code >= 500 or response.status_code == 429:
            raise GatewayTransientError(
                "WeChat token service unavailable", code="token_unavailable"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise GatewayTransientError(
                "WeChat token service returned invalid JSON", code="invalid_upstream_response"
            ) from error
        if not isinstance(body, Mapping):
            raise GatewayTransientError(
                "WeChat token service returned invalid JSON", code="invalid_upstream_response"
            )
        error_code = int(body.get("errcode", 0) or 0)
        if error_code:
            message = str(body.get("errmsg", "WeChat token request failed"))
            if error_code in {40001, 40125, 40164}:
                raise GatewayTerminalError(message, code="token_invalid")
            raise GatewayTerminalError(message, code=f"wechat_{error_code}")
        token = body.get("access_token")
        expires_in = body.get("expires_in", 7200)
        if not isinstance(token, str) or not token:
            raise GatewayTransientError(
                "WeChat token response omitted access_token", code="invalid_upstream_response"
            )
        try:
            ttl = max(60.0, float(expires_in))
        except (TypeError, ValueError):
            ttl = 7200.0
        self._token = token
        self._expires_at = time.time() + ttl
        return token

    def invalidate(self) -> None:
        self._expires_at = 0.0


class WeChatAuthorizerTokenProvider:
    """Refresh a third-party-platform authorizer token with its refresh token."""

    def __init__(
        self,
        authorizer_app_id: str,
        authorizer_refresh_token: str,
        component_app_id: str,
        component_access_token: str,
        *,
        initial_token: str | None = None,
        expires_at: float | None = None,
        base_url: str = "https://api.weixin.qq.com",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.authorizer_app_id = authorizer_app_id
        self.authorizer_refresh_token = authorizer_refresh_token
        self.component_app_id = component_app_id
        self.component_access_token = component_access_token
        self.base_url = base_url.rstrip("/")
        self._client = http_client
        self._token = initial_token
        self._expires_at = expires_at or 0.0
        self._lock = asyncio.Lock()

    async def get_token(self, *, force_refresh: bool = False) -> str:
        now = time.time()
        if not force_refresh and self._token and self._expires_at - now > 60:
            return self._token
        async with self._lock:
            now = time.time()
            if not force_refresh and self._token and self._expires_at - now > 60:
                return self._token
            return await self._refresh()

    async def _refresh(self) -> str:
        body = {
            "component_appid": self.component_app_id,
            "authorizer_appid": self.authorizer_app_id,
            "authorizer_refresh_token": self.authorizer_refresh_token,
        }
        params = {"component_access_token": self.component_access_token}
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        f"{self.base_url}/cgi-bin/component/api_authorizer_token",
                        params=params,
                        json=body,
                    )
            else:
                response = await self._client.post(
                    f"{self.base_url}/cgi-bin/component/api_authorizer_token",
                    params=params,
                    json=body,
                )
        except (httpx.TimeoutException, httpx.NetworkError, OSError) as error:
            raise GatewayTransientError(
                "WeChat authorizer token service unavailable", code="token_unavailable"
            ) from error
        try:
            result = response.json()
        except ValueError as error:
            raise GatewayTransientError(
                "WeChat authorizer token response is invalid",
                code="invalid_upstream_response",
            ) from error
        if not isinstance(result, Mapping):
            raise GatewayTransientError(
                "WeChat authorizer token response is invalid",
                code="invalid_upstream_response",
            )
        error_code = int(result.get("errcode", 0) or 0)
        if response.status_code >= 500 or response.status_code == 429:
            raise GatewayTransientError(
                "WeChat authorizer token service unavailable", code="token_unavailable"
            )
        if response.status_code >= 400 or error_code:
            raise GatewayTerminalError(
                str(result.get("errmsg", "authorizer token refresh failed")),
                code=f"wechat_{error_code or response.status_code}",
            )
        token = result.get("authorizer_access_token")
        if not isinstance(token, str) or not token:
            raise GatewayTransientError(
                "WeChat authorizer token response omitted token",
                code="invalid_upstream_response",
            )
        refreshed = result.get("authorizer_refresh_token")
        if isinstance(refreshed, str) and refreshed:
            self.authorizer_refresh_token = refreshed
        try:
            ttl = max(60.0, float(result.get("expires_in", 7200)))
        except (TypeError, ValueError):
            ttl = 7200.0
        self._token = token
        self._expires_at = time.time() + ttl
        return token


def token_provider_from_secrets(
    app_id: str | None,
    secrets: Mapping[str, Any],
    *,
    base_url: str = "https://api.weixin.qq.com",
    http_client: httpx.AsyncClient | None = None,
) -> AccessTokenProvider:
    authorizer_token = secrets.get("authorizer_access_token")
    refresh_token = secrets.get("authorizer_refresh_token")
    component_app_id = secrets.get("component_app_id")
    component_access_token = secrets.get("component_access_token")
    if all(
        isinstance(value, str) and value
        for value in (
            app_id,
            refresh_token,
            component_app_id,
            component_access_token,
        )
    ):
        expires_at_value = secrets.get("authorizer_token_expires_at")
        try:
            expires_at = float(expires_at_value) if expires_at_value is not None else None
        except (TypeError, ValueError):
            expires_at = None
        return WeChatAuthorizerTokenProvider(
            str(app_id),
            str(refresh_token),
            str(component_app_id),
            str(component_access_token),
            initial_token=str(authorizer_token) if isinstance(authorizer_token, str) else None,
            expires_at=expires_at,
            base_url=base_url,
            http_client=http_client,
        )
    token = secrets.get("access_token") or authorizer_token
    if isinstance(token, str) and token:
        return StaticTokenProvider(token)
    app_secret = secrets.get("app_secret") or secrets.get("secret")
    if (
        not isinstance(app_id, str)
        or not app_id
        or not isinstance(app_secret, str)
        or not app_secret
    ):
        raise GatewayTerminalError(
            "live connection credentials are incomplete", code="credentials_missing"
        )
    return WeChatAccessTokenProvider(app_id, app_secret, base_url=base_url, http_client=http_client)


__all__ = [
    "AccessTokenProvider",
    "StaticTokenProvider",
    "WeChatAuthorizerTokenProvider",
    "WeChatAccessTokenProvider",
    "token_provider_from_secrets",
]
