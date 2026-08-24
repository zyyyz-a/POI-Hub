from __future__ import annotations

import pytest

from poi_admin.webhooks.crypto import (
    decrypt_message,
    encrypt_message,
    verify_signature,
)


def test_signature_uses_sorted_token_timestamp_nonce() -> None:
    assert (
        verify_signature("token", "123", "nonce", "7d4f3b8e90f9c8f5b6d8dbf7d3ad11a7ef2d1b0c")
        is False
    )


def test_encrypt_decrypt_round_trip_validates_app_id() -> None:
    aes_key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    encrypted = encrypt_message("<xml>payload</xml>", aes_key, "wx-test")

    assert decrypt_message(encrypted, aes_key, "wx-test") == "<xml>payload</xml>"
    with pytest.raises(ValueError, match="AppID"):
        decrypt_message(encrypted, aes_key, "wx-other")
