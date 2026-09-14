"""WeChat Pay API v3 signing, verification, JSAPI ordering, and notifications."""

from __future__ import annotations

import base64
import json
import secrets as random_secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class WeChatPayError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _private_key(pem: str) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except (TypeError, ValueError) as error:
        raise WeChatPayError("invalid_merchant_private_key", "微信支付商户私钥无效", 422) from error
    if not isinstance(key, rsa.RSAPrivateKey):
        raise WeChatPayError("invalid_merchant_private_key", "微信支付商户私钥必须是 RSA 私钥", 422)
    return key


def _public_key(pem: str) -> rsa.RSAPublicKey:
    try:
        key = serialization.load_pem_public_key(pem.encode())
    except (TypeError, ValueError) as error:
        raise WeChatPayError("invalid_wechatpay_public_key", "微信支付公钥无效", 422) from error
    if not isinstance(key, rsa.RSAPublicKey):
        raise WeChatPayError("invalid_wechatpay_public_key", "微信支付公钥必须是 RSA 公钥", 422)
    return key


def rsa_sign(message: str, private_key_pem: str) -> str:
    signature = _private_key(private_key_pem).sign(
        message.encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    return base64.b64encode(signature).decode()


def verify_signature(message: str, signature: str, public_key_pem: str) -> bool:
    try:
        decoded = base64.b64decode(signature, validate=True)
        _public_key(public_key_pem).verify(
            decoded, message.encode(), padding.PKCS1v15(), hashes.SHA256()
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def authorization_header(
    method: str,
    path_with_query: str,
    body: str,
    *,
    merchant_id: str,
    serial_no: str,
    private_key_pem: str,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> str:
    resolved_timestamp = timestamp or str(int(time.time()))
    resolved_nonce = nonce or random_secrets.token_hex(16)
    message = (
        f"{method.upper()}\n{path_with_query}\n{resolved_timestamp}\n{resolved_nonce}\n{body}\n"
    )
    signature = rsa_sign(message, private_key_pem)
    return (
        "WECHATPAY2-SHA256-RSA2048 "
        f'mchid="{merchant_id}",nonce_str="{resolved_nonce}",'
        f'signature="{signature}",timestamp="{resolved_timestamp}",serial_no="{serial_no}"'
    )


def verify_http_response(response: httpx.Response, public_key_pem: str) -> None:
    timestamp = response.headers.get("Wechatpay-Timestamp")
    nonce = response.headers.get("Wechatpay-Nonce")
    signature = response.headers.get("Wechatpay-Signature")
    if not timestamp or not nonce or not signature:
        raise WeChatPayError("wechatpay_signature_missing", "微信支付响应缺少验签头")
    message = f"{timestamp}\n{nonce}\n{response.text}\n"
    if not verify_signature(message, signature, public_key_pem):
        raise WeChatPayError("wechatpay_signature_invalid", "微信支付响应验签失败")


def verify_notification(headers: Mapping[str, str], body: bytes, public_key_pem: str) -> None:
    timestamp = headers.get("Wechatpay-Timestamp") or headers.get("wechatpay-timestamp")
    nonce = headers.get("Wechatpay-Nonce") or headers.get("wechatpay-nonce")
    signature = headers.get("Wechatpay-Signature") or headers.get("wechatpay-signature")
    if not timestamp or not nonce or not signature:
        raise WeChatPayError("wechatpay_signature_missing", "支付通知缺少验签头", 401)
    try:
        numeric_timestamp = int(timestamp)
    except ValueError as error:
        raise WeChatPayError("wechatpay_timestamp_invalid", "支付通知时间戳无效", 401) from error
    if abs(int(time.time()) - numeric_timestamp) > 300:
        raise WeChatPayError("wechatpay_notification_expired", "支付通知超过五分钟", 401)
    message = f"{timestamp}\n{nonce}\n{body.decode()}\n"
    if not verify_signature(message, signature, public_key_pem):
        raise WeChatPayError("wechatpay_signature_invalid", "支付通知验签失败", 401)


def decrypt_notification_resource(resource: Mapping[str, Any], api_v3_key: str) -> dict[str, Any]:
    if len(api_v3_key.encode()) != 32:
        raise WeChatPayError("invalid_api_v3_key", "APIv3 密钥必须是 32 字节", 422)
    try:
        nonce = str(resource["nonce"]).encode()
        ciphertext = base64.b64decode(str(resource["ciphertext"]), validate=True)
        associated_data = str(resource.get("associated_data") or "").encode()
        plaintext = AESGCM(api_v3_key.encode()).decrypt(nonce, ciphertext, associated_data)
        value = json.loads(plaintext.decode())
    except (KeyError, ValueError, TypeError) as error:
        raise WeChatPayError("wechatpay_resource_invalid", "支付通知密文无效", 400) from error
    if not isinstance(value, dict):
        raise WeChatPayError("wechatpay_resource_invalid", "支付通知资源格式无效", 400)
    return cast(dict[str, Any], value)


@dataclass(frozen=True, slots=True)
class MiniProgramPayment:
    prepay_id: str
    parameters: dict[str, str]


@dataclass(frozen=True, slots=True)
class RefundResult:
    refund_id: str
    status: str
    raw: dict[str, Any]


class WeChatPayClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self.http_client = http_client

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: str,
        merchant_id: str,
        merchant_serial_no: str,
        merchant_private_key_pem: str,
        wechatpay_public_key_pem: str,
    ) -> dict[str, Any]:
        authorization = authorization_header(
            method,
            path,
            body,
            merchant_id=merchant_id,
            serial_no=merchant_serial_no,
            private_key_pem=merchant_private_key_pem,
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": authorization,
            "User-Agent": "POI-Hub/1.0",
        }
        owns_client = self.http_client is None
        client = self.http_client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.request(
                method,
                "https://api.mch.weixin.qq.com" + path,
                headers=headers,
                content=body.encode("utf-8") if body else None,
            )
        except httpx.HTTPError as error:
            raise WeChatPayError("wechatpay_unavailable", "无法连接微信支付") from error
        finally:
            if owns_client:
                await client.aclose()
        verify_http_response(response, wechatpay_public_key_pem)
        if response.status_code >= 400:
            raise WeChatPayError("wechatpay_rejected", "微信支付请求失败")
        if not response.content:
            return {}
        value = response.json()
        return value if isinstance(value, dict) else {}

    async def create_jsapi_order(
        self,
        *,
        app_id: str,
        merchant_id: str,
        merchant_serial_no: str,
        merchant_private_key_pem: str,
        wechatpay_public_key_pem: str,
        order_no: str,
        description: str,
        amount: int,
        openid: str,
        notify_url: str,
        sub_mchid: str | None = None,
        sp_mchid: str | None = None,
    ) -> MiniProgramPayment:
        path = "/v3/pay/transactions/jsapi"
        if sub_mchid:
            payload: dict[str, Any] = {
                "sp_appid": app_id,
                "sp_mchid": sp_mchid or merchant_id,
                "sub_mchid": sub_mchid,
                "description": description[:127],
                "out_trade_no": order_no,
                "notify_url": notify_url,
                "amount": {"total": amount, "currency": "CNY"},
                "payer": {"sp_openid": openid},
            }
        else:
            payload = {
                "appid": app_id,
                "mchid": merchant_id,
                "description": description[:127],
                "out_trade_no": order_no,
                "notify_url": notify_url,
                "amount": {"total": amount, "currency": "CNY"},
                "payer": {"openid": openid},
            }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        value = await self._call(
            "POST",
            path,
            body=body,
            merchant_id=merchant_id,
            merchant_serial_no=merchant_serial_no,
            merchant_private_key_pem=merchant_private_key_pem,
            wechatpay_public_key_pem=wechatpay_public_key_pem,
        )
        prepay_id = value.get("prepay_id")
        if not isinstance(prepay_id, str) or not prepay_id:
            raise WeChatPayError("wechatpay_response_invalid", "微信支付未返回 prepay_id")
        timestamp = str(int(time.time()))
        nonce = random_secrets.token_hex(16)
        package = f"prepay_id={prepay_id}"
        pay_sign = rsa_sign(
            f"{app_id}\n{timestamp}\n{nonce}\n{package}\n", merchant_private_key_pem
        )
        return MiniProgramPayment(
            prepay_id=prepay_id,
            parameters={
                "timeStamp": timestamp,
                "nonceStr": nonce,
                "package": package,
                "signType": "RSA",
                "paySign": pay_sign,
            },
        )

    async def query_order(
        self,
        *,
        order_no: str,
        merchant_id: str,
        merchant_serial_no: str,
        merchant_private_key_pem: str,
        wechatpay_public_key_pem: str,
        sub_mchid: str | None = None,
        sp_mchid: str | None = None,
    ) -> dict[str, Any]:
        if sub_mchid:
            path = (
                f"/v3/pay/transactions/out-trade-no/{order_no}"
                f"?sp_mchid={sp_mchid or merchant_id}&sub_mchid={sub_mchid}"
            )
        else:
            path = f"/v3/pay/transactions/out-trade-no/{order_no}?mchid={merchant_id}"
        return await self._call(
            "GET",
            path,
            body="",
            merchant_id=merchant_id,
            merchant_serial_no=merchant_serial_no,
            merchant_private_key_pem=merchant_private_key_pem,
            wechatpay_public_key_pem=wechatpay_public_key_pem,
        )

    async def close_order(
        self,
        *,
        order_no: str,
        merchant_id: str,
        merchant_serial_no: str,
        merchant_private_key_pem: str,
        wechatpay_public_key_pem: str,
        sub_mchid: str | None = None,
        sp_mchid: str | None = None,
    ) -> None:
        path = f"/v3/pay/transactions/out-trade-no/{order_no}/close"
        if sub_mchid:
            payload: dict[str, Any] = {"sp_mchid": sp_mchid or merchant_id, "sub_mchid": sub_mchid}
        else:
            payload = {"mchid": merchant_id}
        await self._call(
            "POST",
            path,
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            merchant_id=merchant_id,
            merchant_serial_no=merchant_serial_no,
            merchant_private_key_pem=merchant_private_key_pem,
            wechatpay_public_key_pem=wechatpay_public_key_pem,
        )

    async def create_refund(
        self,
        *,
        out_refund_no: str,
        transaction_id: str,
        total: int,
        refund: int,
        reason: str | None,
        merchant_id: str,
        merchant_serial_no: str,
        merchant_private_key_pem: str,
        wechatpay_public_key_pem: str,
        sub_mchid: str | None = None,
    ) -> RefundResult:
        payload: dict[str, Any] = {
            "transaction_id": transaction_id,
            "out_refund_no": out_refund_no,
            "amount": {"refund": refund, "total": total, "currency": "CNY"},
        }
        if reason:
            payload["reason"] = reason[:80]
        if sub_mchid:
            payload["sub_mchid"] = sub_mchid
        value = await self._call(
            "POST",
            "/v3/refund/domestic/refunds",
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            merchant_id=merchant_id,
            merchant_serial_no=merchant_serial_no,
            merchant_private_key_pem=merchant_private_key_pem,
            wechatpay_public_key_pem=wechatpay_public_key_pem,
        )
        refund_id = value.get("refund_id")
        status = value.get("status")
        return RefundResult(
            refund_id=refund_id if isinstance(refund_id, str) else "",
            status=status if isinstance(status, str) else "",
            raw=value,
        )

    async def query_refund(
        self,
        *,
        out_refund_no: str,
        merchant_id: str,
        merchant_serial_no: str,
        merchant_private_key_pem: str,
        wechatpay_public_key_pem: str,
        sub_mchid: str | None = None,
    ) -> RefundResult:
        path = f"/v3/refund/domestic/refunds/{out_refund_no}"
        if sub_mchid:
            path += f"?sub_mchid={sub_mchid}"
        value = await self._call(
            "GET",
            path,
            body="",
            merchant_id=merchant_id,
            merchant_serial_no=merchant_serial_no,
            merchant_private_key_pem=merchant_private_key_pem,
            wechatpay_public_key_pem=wechatpay_public_key_pem,
        )
        refund_id = value.get("refund_id")
        status = value.get("status")
        return RefundResult(
            refund_id=refund_id if isinstance(refund_id, str) else "",
            status=status if isinstance(status, str) else "",
            raw=value,
        )


__all__ = [
    "MiniProgramPayment",
    "RefundResult",
    "WeChatPayClient",
    "WeChatPayError",
    "authorization_header",
    "decrypt_notification_resource",
    "rsa_sign",
    "verify_http_response",
    "verify_notification",
    "verify_signature",
]
