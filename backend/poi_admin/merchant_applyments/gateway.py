"""Fixed-host API v3 requests, OAEP field encryption and media signing."""

import base64
import hashlib
import json
import re
import time
from typing import Any, cast

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from poi_admin.direct_commerce.wechat_pay import (
    WeChatPayError,
    authorization_header,
    verify_http_response,
)

API_HOST = "https://api.mch.weixin.qq.com"
APPLYMENT_PATH = "/v3/applyment4sub/applyment/"
MEDIA_PATH = "/v3/merchant/media/upload"


class ApplymentGatewayError(Exception):
    def __init__(self, code: str, *, uncertain: bool = False, request_id: str | None = None):
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain
        self.request_id = request_id


class ApplymentGateway:
    def __init__(self, merchant_id: str, bundle: dict[str, Any], client: httpx.AsyncClient):
        self.merchant_id = merchant_id
        self.bundle = bundle
        self.client = client
        for key_name in (
            "merchant_serial_no",
            "merchant_private_key_pem",
            "wechatpay_public_key_pem",
            "wechatpay_public_key_id",
        ):
            if not isinstance(bundle.get(key_name), str) or not bundle[key_name].strip():
                raise ApplymentGatewayError("credentials_incomplete")
        try:
            key = serialization.load_pem_public_key(bundle["wechatpay_public_key_pem"].encode())
            if not isinstance(key, rsa.RSAPublicKey):
                raise ValueError("RSA key required")
            self.public_key = key
        except (ValueError, TypeError):
            raise ApplymentGatewayError("credentials_invalid") from None

    def encrypt(self, text: str) -> str:
        try:
            encrypted = self.public_key.encrypt(
                text.encode("utf-8"),
                padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
            )
            return base64.b64encode(encrypted).decode("ascii")
        except ValueError:
            raise ApplymentGatewayError("sensitive_field_too_long") from None

    async def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        file: tuple[str, bytes, str] | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        body = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
        if method == "GET":
            body = ""
        try:
            signature = authorization_header(
                method,
                path,
                body,
                merchant_id=self.merchant_id,
                serial_no=self.bundle["merchant_serial_no"],
                private_key_pem=self.bundle["merchant_private_key_pem"],
            )
        except WeChatPayError:
            raise ApplymentGatewayError("credentials_invalid") from None
        headers = {
            "Accept": "application/json",
            "Authorization": signature,
            "Wechatpay-Serial": self.bundle["wechatpay_public_key_id"],
            "User-Agent": "POI-Hub-merchant-onboarding/1.0",
        }
        try:
            if file:
                response = await self.client.post(
                    API_HOST + path,
                    headers=headers,
                    follow_redirects=False,
                    files={"meta": (None, body, "application/json"), "file": file},
                )
            else:
                headers["Content-Type"] = "application/json"
                response = await self.client.request(
                    method,
                    API_HOST + path,
                    headers=headers,
                    content=body.encode() if body else None,
                    follow_redirects=False,
                )
        except httpx.HTTPError:
            raise ApplymentGatewayError("wechat_network_error", uncertain=True) from None
        request_id = response.headers.get("Request-ID", "")[:160] or None
        try:
            if response.headers.get("Wechatpay-Serial") != self.bundle["wechatpay_public_key_id"]:
                raise ValueError("unexpected signer")
            verify_http_response(response, self.bundle["wechatpay_public_key_pem"])
            if abs(time.time() - int(response.headers.get("Wechatpay-Timestamp", "0"))) > 300:
                raise ValueError("expired response")
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("invalid response")
        except (WeChatPayError, ValueError, TypeError):
            raise ApplymentGatewayError(
                "wechat_response_unverified",
                uncertain=True,
                request_id=request_id,
            ) from None
        if response.status_code >= 300:
            code = str(value.get("code") or "wechat_request_rejected")
            if not re.fullmatch(r"[A-Za-z0-9_]{1,80}", code):
                code = "wechat_request_rejected"
            if (
                code == "PARAM_ERROR"
                and method == "GET"
                and value.get("message") == "未能找到申请单"
            ):
                code = "APPLYMENT_NOTEXIST"
            raise ApplymentGatewayError(
                code,
                uncertain=response.status_code >= 500,
                request_id=request_id,
            )
        return cast(dict[str, Any], value), request_id

    async def upload(self, kind: str, data: bytes, mime: str) -> str:
        extension = {"image/jpeg": "jpg", "image/png": "png", "image/bmp": "bmp"}[mime]
        name = f"{kind}.{extension}"
        value, _ = await self.request(
            "POST",
            MEDIA_PATH,
            payload={"filename": name, "sha256": hashlib.sha256(data).hexdigest()},
            file=(name, data, mime),
        )
        media_id = value.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise ApplymentGatewayError("wechat_media_id_missing")
        return media_id
