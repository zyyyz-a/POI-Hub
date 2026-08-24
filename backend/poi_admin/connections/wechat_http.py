"""Bounded HTTP transport and error classification for WeChat APIs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .ports import GatewayTerminalError, GatewayTransientError
from .tokens import AccessTokenProvider

TOKEN_ERROR_CODES = {40001, 41001, 42001}


class WeChatHttpClient:
    def __init__(
        self,
        token_provider: AccessTokenProvider,
        *,
        base_url: str = "https://api.weixin.qq.com",
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
        max_response_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.token_provider = token_provider
        self.base_url = base_url.rstrip("/")
        self._client = http_client
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes

    async def post_json(
        self,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        accepted_error_codes: frozenset[int] = frozenset(),
    ) -> dict[str, Any]:
        return await self._request(
            "POST", path, body or {}, accepted_error_codes=accepted_error_codes
        )

    async def get_json(
        self, path: str, *, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", path, None, params=params)

    async def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        *,
        params: Mapping[str, Any] | None = None,
        accepted_error_codes: frozenset[int] = frozenset(),
    ) -> dict[str, Any]:
        token = await self.token_provider.get_token()
        result = await self._send(method, path, body, token=token, params=params)
        if _error_code(result) in TOKEN_ERROR_CODES:
            token = await self.token_provider.get_token(force_refresh=True)
            result = await self._send(method, path, body, token=token, params=params)
        if _error_code(result) in accepted_error_codes:
            return result
        return _check_result(result)

    async def _send(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        *,
        token: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        query = {str(key): value for key, value in (params or {}).items() if value is not None}
        query["access_token"] = token
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(method, url, params=query, json=body)
            else:
                response = await self._client.request(method, url, params=query, json=body)
        except (httpx.TimeoutException, httpx.NetworkError, OSError) as error:
            raise GatewayTransientError(
                "WeChat upstream is temporarily unavailable", code="upstream_unavailable"
            ) from error
        if len(response.content) > self.max_response_bytes:
            raise GatewayTerminalError(
                "WeChat API response exceeded the safety limit", code="response_too_large"
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise GatewayTransientError(
                "WeChat upstream is temporarily unavailable", code="upstream_unavailable"
            )
        if response.status_code >= 400:
            raise GatewayTerminalError(
                "WeChat API rejected the request", code=f"http_{response.status_code}"
            )
        try:
            data = response.json()
        except ValueError as error:
            raise GatewayTransientError(
                "WeChat API returned invalid JSON", code="invalid_upstream_response"
            ) from error
        if not isinstance(data, dict):
            raise GatewayTransientError(
                "WeChat API returned an invalid response", code="invalid_upstream_response"
            )
        return data


def _error_code(body: Mapping[str, Any]) -> int:
    value = body.get("errcode", 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _check_result(body: dict[str, Any]) -> dict[str, Any]:
    code = _error_code(body)
    if code == 0:
        return body
    message = str(body.get("errmsg", "WeChat API request failed"))
    if code in TOKEN_ERROR_CODES or code in {45009, 50001, 50002}:
        raise GatewayTransientError(
            "WeChat upstream request is temporarily unavailable", code=f"wechat_{code}"
        )
    raise GatewayTerminalError(message[:200], code=f"wechat_{code}")


__all__ = ["TOKEN_ERROR_CODES", "WeChatHttpClient"]
