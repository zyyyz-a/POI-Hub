"""Store entry descriptor and WeChat mini-program code generation."""

from __future__ import annotations

import base64
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.crypto import decrypt_secret_bundle
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import ConnectionMode, GatewayError
from poi_admin.connections.tokens import token_provider_from_secrets
from poi_admin.core.config import Settings
from poi_admin.onboarding.models import MiniProgramStoreBinding, PlatformMiniProgram

from .service import DirectCommerceError

DEFAULT_ENTRY_PAGE = "pages/store/index"


async def fetch_unlimited_code(
    provider: Any,
    *,
    scene: str,
    page: str,
    env_version: str,
    base_url: str,
    http_client: httpx.AsyncClient | None = None,
) -> bytes:
    """Call WeChat ``getwxacodeunlimit`` and return the PNG bytes."""

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=20.0)
    try:
        for attempt in range(2):
            token = await provider.get_token(force_refresh=attempt == 1)
            response = await client.post(
                f"{base_url.rstrip('/')}/wxa/getwxacodeunlimit",
                params={"access_token": token},
                json={
                    "scene": scene,
                    "page": page,
                    "check_path": False,
                    "env_version": env_version,
                },
            )
            content_type = response.headers.get("content-type", "")
            if "image" in content_type or response.content[:1] == b"\x89":
                return response.content
            body = response.json() if response.content else {}
            errcode = (
                int(body.get("errcode", 0) or 0) if isinstance(body, dict) else 0
            )
            if errcode in {40001, 42001} and attempt == 0:
                continue
            message = (
                str(body.get("errmsg", "生成小程序码失败"))
                if isinstance(body, dict)
                else "生成小程序码失败"
            )
            raise GatewayError(message, code=f"wechat_{errcode or response.status_code}")
        raise GatewayError("生成小程序码失败", code="wechat_code_failed")
    except httpx.HTTPError as error:
        raise GatewayError("无法连接微信接口", code="wechat_unavailable") from error
    finally:
        if owns_client:
            await client.aclose()


class StoreEntryCodeService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.http_client = http_client

    async def _resources(
        self, tenant_id: str, binding_id: str
    ) -> tuple[MiniProgramStoreBinding, PlatformMiniProgram]:
        binding = await self.session.scalar(
            select(MiniProgramStoreBinding).where(
                MiniProgramStoreBinding.tenant_id == tenant_id,
                MiniProgramStoreBinding.id == binding_id,
            )
        )
        if binding is None:
            raise DirectCommerceError("store_binding_not_found", "门店入口绑定不存在", 404)
        program = await self.session.scalar(
            select(PlatformMiniProgram).where(
                PlatformMiniProgram.id == binding.platform_mini_program_id
            )
        )
        if program is None:
            raise DirectCommerceError("platform_mini_program_not_found", "平台小程序不存在", 404)
        return binding, program

    @staticmethod
    def _descriptor(
        binding: MiniProgramStoreBinding, program: PlatformMiniProgram
    ) -> dict[str, Any]:
        return {
            "store_code": binding.store_code,
            "app_id": program.app_id,
            "page": binding.entry_path or DEFAULT_ENTRY_PAGE,
            "scene": f"store_code={binding.store_code}",
            "entry_path": binding.entry_path,
            "tencent_poi_id": binding.tencent_poi_id,
        }

    async def descriptor(self, tenant_id: str, binding_id: str) -> dict[str, Any]:
        binding, program = await self._resources(tenant_id, binding_id)
        return self._descriptor(binding, program)

    async def generate(
        self, tenant_id: str, binding_id: str, env_version: str
    ) -> dict[str, Any]:
        binding, program = await self._resources(tenant_id, binding_id)
        descriptor = self._descriptor(binding, program)
        base: dict[str, Any] = {
            "available": False,
            "reason": None,
            "image_base64": None,
            **descriptor,
        }
        if not program.connection_id:
            base["reason"] = "平台小程序交易连接未配置"
            return base
        connection = await self.session.scalar(
            select(WeChatConnection).where(WeChatConnection.id == program.connection_id)
        )
        if connection is None or connection.mode != ConnectionMode.LIVE.value:
            base["reason"] = "需要真实的平台小程序连接才能生成门店码"
            return base
        if not connection.encrypted_secrets:
            base["reason"] = "平台小程序连接凭据尚未配置"
            return base
        if not program.app_id:
            base["reason"] = "平台小程序 AppID 未配置"
            return base
        try:
            secrets = decrypt_secret_bundle(
                connection.encrypted_secrets, self.settings.encryption_key
            )
            provider = token_provider_from_secrets(
                program.app_id,
                secrets,
                base_url=self.settings.wechat_api_base_url,
                http_client=self.http_client,
            )
            image = await fetch_unlimited_code(
                provider,
                scene=descriptor["scene"],
                page=descriptor["page"],
                env_version=env_version,
                base_url=self.settings.wechat_api_base_url,
                http_client=self.http_client,
            )
        except GatewayError as error:
            base["reason"] = str(error)
            return base
        except ValueError as error:
            base["reason"] = "平台小程序连接凭据无法解密"
            raise DirectCommerceError("credentials_invalid", str(error), 500) from error
        base["available"] = True
        base["image_base64"] = base64.b64encode(image).decode()
        return base


__all__ = ["StoreEntryCodeService", "fetch_unlimited_code"]
