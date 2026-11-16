"""Fixed-host DeepSeek chat; no tools, business reads or automatic submissions."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from poi_admin.connections.crypto import decrypt_secret_bundle, encrypt_secret_bundle
from poi_admin.core.config import Settings
from poi_admin.core.dependencies import auth_error

from .knowledge import FIELDS, PAGES, SYSTEM_PROMPT

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=3000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)
    page: str = Field(default="/dashboard", max_length=80)
    field: str = Field(default="", max_length=80)
    consent: Literal[True]

    @model_validator(mode="after")
    def bounded_conversation(self) -> ChatRequest:
        if sum(len(item.content) for item in self.messages) > 12_000:
            raise ValueError("conversation too long")
        if self.messages[-1].role != "user":
            raise ValueError("last message must be user")
        if any(
            m.role != ("user" if i % 2 == 0 else "assistant") for i, m in enumerate(self.messages)
        ):
            raise ValueError("invalid conversation order")
        return self


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr


def redact_text(text: str) -> str:
    # Defense in depth, not a promise that all personal information is detectable.
    text = re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----",
        "[私钥已隐藏]",
        text,
    )
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[密钥已隐藏]", text)
    text = re.sub(r"(?<![A-Za-z0-9])\d{15,19}[Xx]?(?![A-Za-z0-9])", "[证件/账户号已隐藏]", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已隐藏]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    return text


class DeepSeekAssistant:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.deepseek_config_path
        self.recent: dict[str, deque[float]] = {}
        self.daily: deque[float] = deque()
        self.active: set[str] = set()

    def read_key(self) -> str:
        if not self.path.exists():
            return ""
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 8192:
                raise ValueError("invalid config")
            bundle = decrypt_secret_bundle(self.path.read_text(), self.settings.encryption_key)
            key = bundle.get("deepseek_api_key")
            if not isinstance(key, str) or not key:
                raise ValueError("invalid config")
            return key
        except (OSError, ValueError):
            raise auth_error(
                "assistant_config_invalid", "助手密钥配置无法读取，请重新配置", 503
            ) from None

    def status(self) -> dict[str, Any]:
        return {"configured": bool(self.read_key()), "model": MODEL, "provider": "DeepSeek"}

    def save_key(self, key: str) -> None:
        key = key.strip()
        if not re.fullmatch(r"sk-[A-Za-z0-9_-]{16,240}", key):
            raise auth_error("invalid_api_key", "请填写有效的 DeepSeek API Key，不是登录密码", 422)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise auth_error("assistant_config_invalid", "密钥保存路径异常，请联系管理员", 503)
        ciphertext = encrypt_secret_bundle({"deepseek_api_key": key}, self.settings.encryption_key)
        fd, temporary = tempfile.mkstemp(prefix=".deepseek-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(ciphertext)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def reserve(self, user_id: str) -> None:
        now = time.monotonic()
        self.recent = {
            key: values for key, values in self.recent.items() if values and values[-1] > now - 3600
        }
        recent = self.recent.setdefault(user_id, deque())
        while recent and recent[0] <= now - 3600:
            recent.popleft()
        while self.daily and self.daily[0] <= now - 86400:
            self.daily.popleft()
        if user_id in self.active or len(self.active) >= 2:
            raise auth_error("assistant_busy", "助手正在回答，请稍后再试", 429)
        if sum(t > now - 60 for t in recent) >= 8 or len(recent) >= 60 or len(self.daily) >= 200:
            raise auth_error("assistant_rate_limited", "本时段咨询次数已达上限，请稍后再试", 429)
        recent.append(now)
        self.daily.append(now)
        self.active.add(user_id)

    async def chat(self, user_id: str, payload: ChatRequest) -> dict[str, str]:
        key = self.read_key()
        if not key:
            raise auth_error(
                "assistant_not_configured", "请先在助手设置中配置 DeepSeek API Key", 503
            )
        self.reserve(user_id)
        try:
            page = PAGES.get(payload.page, "当前为后台其他页面，请让用户说明要填写的字段。")
            field = FIELDS.get(payload.field, "未指定字段。")
            messages = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT + "\n页面说明：" + page + "\n字段说明：" + field,
                }
            ]
            messages += [
                {"role": m.role, "content": redact_text(m.content)} for m in payload.messages
            ]
            # Separate client, fixed destination, no redirects/retries or model tool calls.
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(50, connect=10), follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream(
                    "POST",
                    API_URL,
                    headers={"Authorization": "Bearer " + key},
                    json={
                        "model": MODEL,
                        "messages": messages,
                        "max_tokens": 2048,
                        "stream": False,
                        "thinking": {"type": "disabled"},
                    },
                ) as response:
                    if response.status_code != 200:
                        code = response.status_code
                        if code == 401:
                            raise auth_error(
                                "assistant_key_rejected", "DeepSeek密钥无效，请检查助手设置", 502
                            )
                        if code == 402:
                            raise auth_error(
                                "assistant_no_balance", "DeepSeek账户余额不足，请到其平台充值", 502
                            )
                        if code == 429:
                            raise auth_error(
                                "assistant_provider_busy", "DeepSeek请求繁忙，请稍后重试", 503
                            )
                        raise auth_error(
                            "assistant_upstream_error", "DeepSeek暂未正常响应，请稍后重试", 502
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 256 * 1024:
                            raise ValueError("response too large")
            result = json.loads(body)
            answer = result["choices"][0]["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("empty reply")
            return {"reply": redact_text(answer[:12_000]), "model": MODEL}
        except httpx.TimeoutException:
            raise auth_error(
                "assistant_timeout", "DeepSeek响应超时，未自动重试；请稍后再问", 504
            ) from None
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise auth_error(
                "assistant_unavailable", "暂时无法取得DeepSeek回答，请稍后重试", 502
            ) from None
        finally:
            self.active.discard(user_id)
