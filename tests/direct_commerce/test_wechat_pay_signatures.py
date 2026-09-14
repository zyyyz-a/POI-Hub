from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from poi_admin.direct_commerce.wechat_pay import (
    WeChatPayError,
    authorization_header,
    decrypt_notification_resource,
    verify_notification,
)


def keys() -> tuple[rsa.RSAPrivateKey, str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, private_pem, public_pem


def test_api_v3_authorization_signs_exact_canonical_message() -> None:
    private, private_pem, _ = keys()
    body = '{"amount":{"total":1}}'
    header = authorization_header(
        "POST",
        "/v3/pay/transactions/jsapi",
        body,
        merchant_id="1900000109",
        serial_no="SERIAL001",
        private_key_pem=private_pem,
        timestamp="1700000000",
        nonce="fixed-nonce",
    )
    signature = header.split('signature="', 1)[1].split('"', 1)[0]
    message = 'POST\n/v3/pay/transactions/jsapi\n1700000000\nfixed-nonce\n{"amount":{"total":1}}\n'
    private.public_key().verify(
        base64.b64decode(signature),
        message.encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_notification_must_verify_before_api_v3_decryption() -> None:
    private, _, public_pem = keys()
    api_v3_key = "12345678901234567890123456789012"
    transaction = {
        "appid": "wx-test",
        "mchid": "1900000109",
        "out_trade_no": "ORDER-1",
        "trade_state": "SUCCESS",
        "amount": {"total": 1},
    }
    nonce = b"123456789012"
    associated_data = b"transaction"
    ciphertext = AESGCM(api_v3_key.encode()).encrypt(
        nonce, json.dumps(transaction).encode(), associated_data
    )
    resource = {
        "nonce": nonce.decode(),
        "associated_data": associated_data.decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }
    body = json.dumps({"resource": resource}, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    message = f"{timestamp}\nnotify-nonce\n{body.decode()}\n"
    signature = base64.b64encode(
        private.sign(message.encode(), padding.PKCS1v15(), hashes.SHA256())
    ).decode()
    headers = {
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": "notify-nonce",
        "Wechatpay-Signature": signature,
    }
    verify_notification(headers, body, public_pem)
    assert decrypt_notification_resource(resource, api_v3_key) == transaction

    headers["Wechatpay-Signature"] = base64.b64encode(b"tampered").decode()
    with pytest.raises(WeChatPayError, match="验签失败"):
        verify_notification(headers, body, public_pem)
