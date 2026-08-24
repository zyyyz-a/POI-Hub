"""WeChat callback signatures and AES-256-CBC message framing."""

from __future__ import annotations

import base64
import hashlib
import os
import struct
from hmac import compare_digest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def verify_signature(
    token: str, timestamp: str, nonce: str, signature: str, encrypt: str | None = None
) -> bool:
    values = [token, timestamp, nonce] + ([encrypt] if encrypt is not None else [])
    expected = hashlib.sha1("".join(sorted(values)).encode("utf-8")).hexdigest()
    return compare_digest(expected, signature)


def _key(value: str) -> bytes:
    candidate = value.strip()
    if len(candidate) == 64:
        try:
            return bytes.fromhex(candidate)
        except ValueError:
            pass
    try:
        decoded = base64.b64decode(candidate + "=", validate=False)
    except Exception as error:  # pragma: no cover - defensive boundary
        raise ValueError("invalid EncodingAESKey") from error
    if len(decoded) != 32:
        raise ValueError("invalid EncodingAESKey")
    return decoded


def _unpad(value: bytes) -> bytes:
    if not value:
        raise ValueError("invalid PKCS#7 padding")
    size = value[-1]
    if size < 1 or size > 32 or value[-size:] != bytes([size]) * size:
        raise ValueError("invalid PKCS#7 padding")
    return value[:-size]


def encrypt_message(message: str, encoding_aes_key: str, app_id: str) -> str:
    key = _key(encoding_aes_key)
    raw = (
        os.urandom(16)
        + struct.pack("!I", len(message.encode("utf-8")))
        + message.encode("utf-8")
        + app_id.encode("utf-8")
    )
    pad = 32 - (len(raw) % 32)
    encrypted = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    return base64.b64encode(
        encrypted.update(raw + bytes([pad]) * pad) + encrypted.finalize()
    ).decode("ascii")


def decrypt_message(encrypted: str, encoding_aes_key: str, app_id: str) -> str:
    key = _key(encoding_aes_key)
    try:
        ciphertext = base64.b64decode(encrypted)
        decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
        frame = _unpad(decryptor.update(ciphertext) + decryptor.finalize())
        if len(frame) < 20:
            raise ValueError("invalid callback frame")
        length = struct.unpack("!I", frame[16:20])[0]
        end = 20 + length
        if end > len(frame):
            raise ValueError("invalid callback message length")
        message = frame[20:end].decode("utf-8")
        embedded_app_id = frame[end:].decode("utf-8")
        if not compare_digest(embedded_app_id, app_id):
            raise ValueError("AppID does not match callback connection")
        return message
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("invalid encrypted callback") from error


__all__ = ["decrypt_message", "encrypt_message", "verify_signature"]
