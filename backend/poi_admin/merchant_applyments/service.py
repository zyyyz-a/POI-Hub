"""Drafts, explicit real submission, reconciliation, and safe payment-profile linking."""

import base64
import re
from datetime import UTC
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.crypto import decrypt_secret_bundle, encrypt_secret_bundle
from poi_admin.connections.models import WeChatConnection
from poi_admin.core.config import Settings
from poi_admin.direct_commerce.models import MerchantPaymentProfile
from poi_admin.stores.models import Store

from .contracts import ATTACHMENT_KINDS, build_payload, validate_fields
from .gateway import APPLYMENT_PATH, ApplymentGateway, ApplymentGatewayError
from .limits import MAX_IMAGE_BYTES
from .models import ApplymentAttachment, MerchantApplyment, utcnow
from .schemas import ApplymentResponse, AttachmentResponse, IndividualFields

EDITABLE = {"draft", "rejected", "needs_edit"}
OFFICIAL_STATES = {
    "APPLYMENT_STATE_EDITTING": "needs_edit",
    "APPLYMENT_STATE_AUDITING": "reviewing",
    "APPLYMENT_STATE_REJECTED": "rejected",
    "APPLYMENT_STATE_TO_BE_CONFIRMED": "needs_confirmation",
    "APPLYMENT_STATE_TO_BE_SIGNED": "needs_signature",
    "APPLYMENT_STATE_SIGNING": "opening",
    "APPLYMENT_STATE_FINISHED": "finished",
    "APPLYMENT_STATE_CANCELED": "canceled",
}


class ApplymentError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def safe_sign_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme == "https"
            and url.hostname in {"pay.weixin.qq.com", "pay.wechatpay.cn"}
            and not url.username
            and not url.password
            and url.port in {None, 443}
        ):
            return value
    except ValueError:
        pass
    return None


def safe_diagnostic(value: object) -> str:
    text = str(value or "")[:1000]
    text = re.sub(r"\b\d{6,}[0-9Xx]?\b", "[号码已隐藏]", text)
    return re.sub(r"[^\s@]+@[^\s@]+", "[邮箱已隐藏]", text)


class ApplymentService:
    def __init__(self, session: AsyncSession, settings: Settings, client: httpx.AsyncClient):
        self.session, self.settings, self.client = session, settings, client

    async def get(self, tenant_id: str, application_id: str) -> MerchantApplyment:
        row = await self.session.scalar(
            select(MerchantApplyment).where(
                MerchantApplyment.id == application_id,
                MerchantApplyment.tenant_id == tenant_id,
            )
        )
        if row is None:
            raise ApplymentError("applyment_not_found", "入驻申请不存在", 404)
        return row

    async def connection(self, tenant_id: str, connection_id: str) -> WeChatConnection:
        connection = await self.session.scalar(
            select(WeChatConnection).where(
                WeChatConnection.id == connection_id,
                WeChatConnection.tenant_id == tenant_id,
                WeChatConnection.capability == "mini_program_commerce",
            )
        )
        if connection is None or connection.mode != "live" or not connection.merchant_id:
            raise ApplymentError("live_connection_required", "请选择本商户的真实微信支付连接", 422)
        if not connection.app_id or not re.fullmatch(r"wx[0-9a-f]{16}", connection.app_id):
            raise ApplymentError(
                "platform_appid_required", "请先在支付连接中填写平台小程序AppID", 422
            )
        return connection

    def fields(self, row: MerchantApplyment) -> IndividualFields:
        try:
            return IndividualFields.model_validate(
                decrypt_secret_bundle(row.encrypted_fields, self.settings.encryption_key)
            )
        except ValueError:
            raise ApplymentError(
                "draft_decryption_failed", "资料无法读取，请联系平台管理员", 500
            ) from None

    async def attachments(self, application_id: str) -> list[ApplymentAttachment]:
        return list(
            (
                await self.session.scalars(
                    select(ApplymentAttachment)
                    .where(
                        ApplymentAttachment.applyment_id == application_id,
                    )
                    .order_by(ApplymentAttachment.kind)
                )
            ).all()
        )

    async def present(self, row: MerchantApplyment, *, detail: bool = True) -> ApplymentResponse:
        response = ApplymentResponse(
            id=row.id,
            store_id=row.store_id,
            connection_id=row.connection_id,
            business_code=row.business_code,
            sp_mchid=row.sp_mchid,
            platform_app_id=row.platform_app_id,
            state=row.state,
            applyment_id=row.applyment_id,
            sub_mchid=row.sub_mchid,
            last_error_code=row.last_error_code,
            last_request_id=row.last_request_id,
            version=row.version,
            updated_at=row.updated_at,
            editable=row.state in EDITABLE,
        )
        if detail:
            fields = self.fields(row)
            files = await self.attachments(row.id)
            response.fields = fields
            response.attachments = [
                AttachmentResponse(kind=item.kind, size_bytes=item.size_bytes) for item in files
            ]
            response.issues = validate_fields(fields, {item.kind for item in files})
            if row.encrypted_result:
                result = decrypt_secret_bundle(row.encrypted_result, self.settings.encryption_key)
                if row.state in {"needs_confirmation", "needs_signature", "opening"}:
                    response.sign_url = safe_sign_url(result.get("sign_url"))
                details = result.get("audit_detail")
                if isinstance(details, list):
                    response.audit_details = [
                        safe_diagnostic(item.get("reject_reason"))
                        for item in details[:20]
                        if isinstance(item, dict)
                    ]
        return response

    async def create(self, tenant_id: str, store_id: str, connection_id: str) -> MerchantApplyment:
        store = await self.session.scalar(
            select(Store).where(
                Store.id == store_id,
                Store.tenant_id == tenant_id,
            )
        )
        if store is None:
            raise ApplymentError("store_not_found", "门店不存在", 404)
        connection = await self.connection(tenant_id, connection_id)
        fields = IndividualFields(store_name=store.name, store_address=store.address)
        row = MerchantApplyment(
            tenant_id=tenant_id,
            store_id=store_id,
            connection_id=connection_id,
            sp_mchid=connection.merchant_id or "",
            platform_app_id=connection.app_id or "",
            business_code="POI_" + uuid4().hex,
            encrypted_fields=encrypt_secret_bundle(
                fields.model_dump(), self.settings.encryption_key
            ),
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ApplymentError("applyment_exists", "该门店已有入驻申请，请打开已有申请") from None
        await self.session.refresh(row)
        return row

    async def claim(
        self,
        row: MerchantApplyment,
        version: int,
        changes: dict[str, Any],
        *,
        states: set[str] | None = None,
    ) -> None:
        result = await self.session.execute(
            update(MerchantApplyment)
            .where(
                MerchantApplyment.id == row.id,
                MerchantApplyment.version == version,
                MerchantApplyment.state.in_(states or EDITABLE),
            )
            .values(**changes, version=version + 1, updated_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            await self.session.rollback()
            raise ApplymentError("applyment_conflict", "资料或申请状态已变化，请刷新后重试")

    async def save(
        self,
        row: MerchantApplyment,
        version: int,
        fields: IndividualFields,
    ) -> MerchantApplyment:
        await self.claim(
            row,
            version,
            {
                "encrypted_fields": encrypt_secret_bundle(
                    fields.model_dump(), self.settings.encryption_key
                ),
                "last_error_code": None,
            },
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def attach(
        self,
        row: MerchantApplyment,
        version: int,
        kind: str,
        data: bytes,
    ) -> MerchantApplyment:
        if kind not in ATTACHMENT_KINDS:
            raise ApplymentError("invalid_attachment_kind", "不支持的资料类型", 422)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ApplymentError("image_too_large", "处理后的照片不能超过微信要求的5MB", 413)
        if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif len(data) >= 20 and data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
            mime = "image/jpeg"
        elif len(data) >= 26 and data.startswith(b"BM"):
            mime = "image/bmp"
        else:
            raise ApplymentError("invalid_image", "请上传真实的JPG、PNG或BMP照片", 422)
        await self.claim(row, version, {})
        await self.session.execute(
            delete(ApplymentAttachment).where(
                ApplymentAttachment.applyment_id == row.id,
                ApplymentAttachment.kind == kind,
            )
        )
        self.session.add(
            ApplymentAttachment(
                applyment_id=row.id,
                kind=kind,
                content_type=mime,
                size_bytes=len(data),
                encrypted_content=encrypt_secret_bundle(
                    {"content": base64.b64encode(data).decode("ascii")},
                    self.settings.encryption_key,
                ),
            )
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def remove_attachment(
        self,
        row: MerchantApplyment,
        version: int,
        kind: str,
    ) -> MerchantApplyment:
        await self.claim(row, version, {})
        await self.session.execute(
            delete(ApplymentAttachment).where(
                ApplymentAttachment.applyment_id == row.id,
                ApplymentAttachment.kind == kind,
            )
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def gateway(self, row: MerchantApplyment) -> tuple[ApplymentGateway, str]:
        connection = await self.connection(row.tenant_id, row.connection_id)
        if connection.merchant_id != row.sp_mchid:
            raise ApplymentError("service_provider_changed", "服务商号已变化，请联系管理员核对")
        if connection.app_id != row.platform_app_id:
            raise ApplymentError("platform_appid_changed", "平台小程序AppID已变化，请先核对原申请")
        try:
            bundle = decrypt_secret_bundle(
                connection.encrypted_secrets or "", self.settings.encryption_key
            )
            return ApplymentGateway(row.sp_mchid, bundle, self.client), connection.app_id or ""
        except ValueError:
            raise ApplymentError("credentials_invalid", "支付连接凭据无法读取", 422) from None

    async def submit(
        self,
        row: MerchantApplyment,
        version: int,
        actor_id: str,
    ) -> MerchantApplyment:
        if not self.settings.wechat_applyment_submit_enabled:
            raise ApplymentError(
                "submission_disabled", "真实进件提交尚未开启，可先保存和核对草稿", 403
            )
        fields = self.fields(row)
        files = await self.attachments(row.id)
        issues = validate_fields(fields, {item.kind for item in files})
        if issues:
            raise ApplymentError("application_incomplete", "资料未完整，请按页面缺项提示补充", 422)
        try:
            gateway, app_id = await self.gateway(row)
        except ApplymentGatewayError as error:
            raise ApplymentError(
                error.code, "支付签名或验签配置不完整，请联系管理员", 422
            ) from None
        await self.claim(
            row,
            version,
            {
                "state": "submitting",
                "submitted_at": utcnow(),
                "authorized_by": actor_id,
                "last_error_code": None,
            },
        )
        await self.session.commit()
        await self.session.refresh(row)
        sent_application = False
        changes: dict[str, Any]
        try:
            media: dict[str, str] = {}
            for file in files:
                bundle = decrypt_secret_bundle(file.encrypted_content, self.settings.encryption_key)
                data = base64.b64decode(bundle["content"])
                media[file.kind] = await gateway.upload(file.kind, data, file.content_type)
            payload = build_payload(fields, media, row.business_code, app_id, gateway)
            sent_application = True
            value, request_id = await gateway.request("POST", APPLYMENT_PATH, payload=payload)
            applyment_id = str(value.get("applyment_id") or "")
            if not re.fullmatch(r"\d{1,64}", applyment_id):
                raise ApplymentGatewayError("wechat_application_id_missing", uncertain=True)
            if row.applyment_id and row.applyment_id != applyment_id:
                raise ApplymentGatewayError("wechat_application_mismatch", uncertain=True)
            changes = {
                "applyment_id": applyment_id,
                "state": "reviewing",
                "last_request_id": request_id,
                "encrypted_result": encrypt_secret_bundle(value, self.settings.encryption_key),
            }
        except ApplymentGatewayError as error:
            state = "submission_unknown" if sent_application and error.uncertain else "draft"
            if sent_application and error.code in {"PROCESSING", "RESOURCE_ALREADY_EXISTS"}:
                state = "submission_unknown"
            changes = {
                "state": state,
                "last_error_code": error.code,
                "last_request_id": error.request_id,
            }
        except (ValueError, TypeError, KeyError):
            changes = {
                "state": "submission_unknown" if sent_application else "draft",
                "last_error_code": "application_processing_failed",
            }
        await self.claim(row, row.version, changes, states={"submitting"})
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def sync(self, row: MerchantApplyment, version: int) -> MerchantApplyment:
        if row.version != version:
            raise ApplymentError("applyment_conflict", "申请已变化，请刷新后重试")
        if row.submitted_at is None:
            raise ApplymentError("application_not_submitted", "请先提交真实入驻申请")
        elapsed = (utcnow() - row.submitted_at.replace(tzinfo=UTC)).total_seconds()
        if row.state == "submitting" and elapsed < 600:
            raise ApplymentError("submission_in_progress", "申请正在提交，请等待操作完成后查询")
        try:
            gateway, _ = await self.gateway(row)
            value, request_id = await gateway.request(
                "GET",
                APPLYMENT_PATH + "business_code/" + row.business_code,
            )
        except ApplymentGatewayError as error:
            changes: dict[str, Any] = {
                "last_error_code": error.code,
                "last_request_id": error.request_id,
            }
            if (
                error.code == "APPLYMENT_NOTEXIST"
                and row.state
                in {
                    "submitting",
                    "submission_unknown",
                }
                and elapsed >= 300
            ):
                changes["state"] = "draft"
            await self.claim(row, version, changes, states={row.state})
        else:
            applyment_id = str(value.get("applyment_id") or "")
            if (
                not re.fullmatch(r"\d{1,64}", applyment_id)
                or (row.applyment_id and row.applyment_id != applyment_id)
                or value.get("business_code", row.business_code) != row.business_code
            ):
                raise ApplymentError(
                    "wechat_application_mismatch", "微信返回的申请单与当前门店不匹配，请联系管理员"
                )
            official_state = value.get("applyment_state")
            state = OFFICIAL_STATES.get(str(official_state), "unknown")
            sub_mchid = str(value.get("sub_mchid") or "")
            if state == "finished" and not re.fullmatch(r"\d{6,32}", sub_mchid):
                state = "unknown"
            # Never regress a completed application on a stale/unexpected provider response.
            if row.state == "finished" and state != "finished":
                raise ApplymentError(
                    "unexpected_provider_state", "微信返回状态异常，请联系管理员核对"
                )
            if row.sub_mchid and row.sub_mchid != sub_mchid:
                raise ApplymentError(
                    "wechat_submerchant_mismatch", "微信返回的子商户号已变化，禁止覆盖原收款账户"
                )
            await self.claim(
                row,
                version,
                {
                    "state": state,
                    "encrypted_result": encrypt_secret_bundle(value, self.settings.encryption_key),
                    "applyment_id": applyment_id,
                    "sub_mchid": sub_mchid if state == "finished" else None,
                    "last_error_code": None if state != "unknown" else "unknown_provider_state",
                    "last_request_id": request_id,
                },
                states={row.state},
            )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def link_payment(self, row: MerchantApplyment, version: int) -> str:
        if row.state != "finished" or not row.sub_mchid:
            raise ApplymentError("application_not_finished", "微信确认入驻完成后才能关联支付档案")
        connection = await self.connection(row.tenant_id, row.connection_id)
        if connection.merchant_id != row.sp_mchid:
            raise ApplymentError("service_provider_changed", "服务商号已变化，请先核对")
        if connection.app_id != row.platform_app_id:
            raise ApplymentError(
                "platform_appid_changed", "平台小程序AppID已变化，禁止关联错误账户"
            )
        await self.claim(row, version, {}, states={"finished"})
        profile = await self.session.scalar(
            select(MerchantPaymentProfile).where(
                MerchantPaymentProfile.tenant_id == row.tenant_id,
                MerchantPaymentProfile.store_id == row.store_id,
            )
        )
        if profile is not None and profile.status == "active":
            if (
                profile.mode != "partner"
                or profile.sp_mchid != row.sp_mchid
                or profile.sub_mchid != row.sub_mchid
                or profile.connection_id != row.connection_id
            ):
                await self.session.rollback()
                raise ApplymentError(
                    "active_payment_conflict", "已有启用的不同收款账户，禁止自动替换"
                )
        else:
            if profile is None:
                profile = MerchantPaymentProfile(tenant_id=row.tenant_id, store_id=row.store_id)
                self.session.add(profile)
            profile.mode, profile.sp_mchid, profile.sub_mchid = (
                "partner",
                row.sp_mchid,
                row.sub_mchid,
            )
            profile.mchid, profile.connection_id = None, row.connection_id
            profile.verified, profile.status = True, "draft"
            if profile.version is not None:
                profile.version += 1
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ApplymentError(
                "payment_profile_conflict", "支付档案已变化，请刷新后核对"
            ) from None
        await self.session.refresh(profile)
        await self.session.refresh(row)
        return profile.id
