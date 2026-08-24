"""Encryption and redaction helpers for connection credentials and diagnostics."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NON_SECRET_KEYS = {"name", "display_name", "merchant_product_id", "status"}
_SECRET_MARKER = "[REDACTED]"


def _key(master_key: str) -> bytes:
    if not master_key:
        raise ValueError("encryption master key cannot be empty")
    return hashlib.sha256(master_key.encode("utf-8")).digest()


def encrypt_secret_bundle(bundle: Mapping[str, Any], master_key: str) -> str:
    """Encrypt a JSON-compatible credential bundle using AES-256-GCM."""

    plaintext = json.dumps(dict(bundle), ensure_ascii=False, separators=(",", ":")).encode()
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key(master_key)).encrypt(nonce, plaintext, b"poi-connection-v1")

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    return "v1." + encode(nonce) + "." + encode(ciphertext)


def decrypt_secret_bundle(value: str, master_key: str) -> dict[str, Any]:
    """Decrypt a bundle produced by encrypt_secret_bundle."""

    try:
        version, nonce_encoded, cipher_encoded = value.split(".", 2)
        if version != "v1":
            raise ValueError("unsupported ciphertext version")

        def decode(item: str) -> bytes:
            return base64.urlsafe_b64decode(item + "=" * (-len(item) % 4))

        plaintext = AESGCM(_key(master_key)).decrypt(
            decode(nonce_encoded), decode(cipher_encoded), b"poi-connection-v1"
        )
        result = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid encrypted secret bundle") from exc
    if not isinstance(result, dict):
        raise ValueError("encrypted secret bundle must contain an object")
    return result


def _is_sensitive(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    if normalized in _NON_SECRET_KEYS:
        return False
    markers = ("secret", "token", "password", "authorization", "openid", "phone", "voucher")
    code_fields = {"auth_code", "codes", "consume_code", "coupon_code", "voucher_code"}
    return normalized in code_fields or any(marker in normalized for marker in markers)


def redact_secrets(value: Any) -> Any:
    """Return a JSON-like copy with credential and personal fields redacted."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_sensitive(str(key)) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    return value


__all__ = ["decrypt_secret_bundle", "encrypt_secret_bundle", "redact_secrets"]
