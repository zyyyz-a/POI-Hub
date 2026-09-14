"""Platform-level store entry resolution and commerce over one shared AppID."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

import httpx
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.billing.service import BillingService
from poi_admin.connections.crypto import decrypt_secret_bundle, encrypt_secret_bundle
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.core.config import Settings
from poi_admin.onboarding.models import MiniProgramStoreBinding, PlatformMiniProgram
from poi_admin.stores.models import Store

from .models import (
    DirectAppointment,
    DirectOrder,
    DirectProduct,
    DirectRefund,
    DirectVoucher,
    MerchantPaymentProfile,
    PlatformConsumerIdentity,
    PlatformConsumerSession,
    utcnow,
)
from .service import DirectCommerceError, DirectCommerceService, _aware, _hash, _masked_phone
from .wechat_pay import (
    WeChatPayClient,
    WeChatPayError,
    decrypt_notification_resource,
    verify_notification,
)


@dataclass(frozen=True, slots=True)
class StoreEntry:
    program: PlatformMiniProgram
    binding: MiniProgramStoreBinding
    store: Store
    profile: MerchantPaymentProfile | None


@dataclass(frozen=True, slots=True)
class PaymentRoute:
    merchant_id: str
    app_id: str
    sub_mchid: str | None
    sp_mchid: str | None


class PlatformCommerceService:
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

    async def resolve(self, store_code: str) -> StoreEntry:
        binding = await self.session.scalar(
            select(MiniProgramStoreBinding).where(
                MiniProgramStoreBinding.store_code == store_code
            )
        )
        if binding is None:
            raise DirectCommerceError("store_entry_not_found", "门店入口不存在", 404)
        program = await self.session.scalar(
            select(PlatformMiniProgram).where(
                PlatformMiniProgram.id == binding.platform_mini_program_id
            )
        )
        store = await self.session.scalar(
            select(Store).where(
                Store.id == binding.store_id, Store.tenant_id == binding.tenant_id
            )
        )
        if program is None or store is None:
            raise DirectCommerceError("store_entry_not_found", "门店入口不存在", 404)
        profile = await self.session.scalar(
            select(MerchantPaymentProfile).where(
                MerchantPaymentProfile.tenant_id == binding.tenant_id,
                MerchantPaymentProfile.store_id == binding.store_id,
            )
        )
        return StoreEntry(program=program, binding=binding, store=store, profile=profile)

    async def blockers(self, entry: StoreEntry) -> list[str]:
        blockers: list[str] = []
        if entry.program.status != "active":
            blockers.append("平台小程序未启用")
        if not entry.program.app_id:
            blockers.append("平台小程序 AppID 未配置")
        if not entry.program.callback_configured:
            blockers.append("支付回调未配置")
        if entry.binding.status != "active":
            blockers.append("门店入口未启用")
        if entry.store.status != "active":
            blockers.append("门店已停业")
        if entry.profile is None:
            blockers.append("门店支付档案未配置")
        else:
            blockers.extend(
                DirectCommerceService.payment_profile_blockers(entry.profile)
            )
        blockers.extend(
            await BillingService(self.session).subscription_blockers(
                entry.binding.tenant_id
            )
        )
        return blockers

    async def require_tradable(self, entry: StoreEntry) -> None:
        blockers = await self.blockers(entry)
        if blockers:
            raise DirectCommerceError(
                "store_not_tradable", "暂不能营业：" + "、".join(blockers), 409
            )

    async def login(self, store_code: str, code: str) -> tuple[str, datetime]:
        entry = await self.resolve(store_code)
        await self.require_tradable(entry)
        connection = await self._program_connection(entry.program)
        openid = await self._openid_from_code(entry.program, connection, code)
        openid_hash = _hash(openid)
        identity = await self.session.scalar(
            select(PlatformConsumerIdentity).where(
                PlatformConsumerIdentity.platform_mini_program_id == entry.program.id,
                PlatformConsumerIdentity.openid_hash == openid_hash,
            )
        )
        if identity is None:
            identity = PlatformConsumerIdentity(
                platform_mini_program_id=entry.program.id,
                openid_hash=openid_hash,
                openid_ciphertext=encrypt_secret_bundle(
                    {"openid": openid}, self.settings.encryption_key
                ),
            )
            self.session.add(identity)
            await self.session.flush()
        identity.last_login_at = utcnow()
        access_token = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(days=7)
        self.session.add(
            PlatformConsumerSession(
                identity_id=identity.id,
                token_hash=_hash(access_token),
                expires_at=expires_at,
            )
        )
        await self.session.commit()
        return access_token, expires_at

    async def consumer(
        self, access_token: str, store_code: str, *, tradable: bool = True
    ) -> tuple[StoreEntry, PlatformConsumerIdentity]:
        entry = await self.resolve(store_code)
        if tradable:
            await self.require_tradable(entry)
        row = await self.session.scalar(
            select(PlatformConsumerIdentity)
            .join(
                PlatformConsumerSession,
                PlatformConsumerSession.identity_id == PlatformConsumerIdentity.id,
            )
            .where(
                PlatformConsumerSession.token_hash == _hash(access_token),
                PlatformConsumerSession.revoked_at.is_(None),
                PlatformConsumerSession.expires_at > utcnow(),
                PlatformConsumerIdentity.platform_mini_program_id == entry.program.id,
            )
        )
        if row is None:
            raise DirectCommerceError(
                "consumer_authentication_required", "顾客登录已失效", 401
            )
        return entry, row

    async def products(self, store_code: str) -> list[DirectProduct]:
        entry = await self.resolve(store_code)
        await self.require_tradable(entry)
        rows = await self.session.execute(
            select(DirectProduct)
            .where(
                DirectProduct.tenant_id == entry.binding.tenant_id,
                DirectProduct.store_id == entry.store.id,
                DirectProduct.status == "listed",
                DirectProduct.stock > 0,
            )
            .order_by(DirectProduct.created_at.desc())
        )
        return list(rows.scalars().all())

    async def product(self, store_code: str, product_id: str) -> DirectProduct:
        entry = await self.resolve(store_code)
        await self.require_tradable(entry)
        row = await self.session.scalar(
            select(DirectProduct).where(
                DirectProduct.id == product_id,
                DirectProduct.tenant_id == entry.binding.tenant_id,
                DirectProduct.store_id == entry.store.id,
                DirectProduct.status == "listed",
            )
        )
        if row is None:
            raise DirectCommerceError("product_not_available", "商品当前不可购买", 404)
        return row

    async def orders(self, store_code: str, consumer_id: str) -> list[DirectOrder]:
        entry = await self.resolve(store_code)
        rows = await self.session.execute(
            select(DirectOrder)
            .where(
                DirectOrder.tenant_id == entry.binding.tenant_id,
                DirectOrder.store_binding_id == entry.binding.id,
                DirectOrder.platform_consumer_id == consumer_id,
            )
            .order_by(DirectOrder.created_at.desc())
        )
        return list(rows.scalars().all())

    async def request_refund(
        self,
        store_code: str,
        consumer: PlatformConsumerIdentity,
        order_id: str,
        reason: str | None,
        idempotency_key: str,
    ) -> DirectRefund:
        entry = await self.resolve(store_code)
        order = await self.order(store_code, consumer.id, order_id)
        service = DirectCommerceService(
            self.session, self.settings, http_client=self.http_client
        )
        return await service.request_consumer_refund(
            entry.binding.tenant_id,
            order.id,
            consumer.id,
            reason,
            idempotency_key,
        )

    async def create_order(
        self,
        store_code: str,
        consumer: PlatformConsumerIdentity,
        product_id: str,
        quantity: int,
        idempotency_key: str,
    ) -> DirectOrder:
        entry = await self.resolve(store_code)
        await self.require_tradable(entry)
        existing = await self.session.scalar(
            select(DirectOrder).where(
                DirectOrder.tenant_id == entry.binding.tenant_id,
                DirectOrder.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.platform_consumer_id != consumer.id
                or existing.product_id != product_id
            ):
                raise DirectCommerceError(
                    "idempotency_conflict", "幂等键已用于其他订单", 409
                )
            return existing
        product = await self.session.scalar(
            select(DirectProduct).where(
                DirectProduct.id == product_id,
                DirectProduct.tenant_id == entry.binding.tenant_id,
                DirectProduct.store_id == entry.store.id,
            )
        )
        if product is None or product.status != "listed":
            raise DirectCommerceError("product_not_available", "商品当前不可购买", 409)
        reserved = await self.session.execute(
            update(DirectProduct)
            .where(
                DirectProduct.id == product.id,
                DirectProduct.status == "listed",
                DirectProduct.stock >= quantity,
            )
            .values(stock=DirectProduct.stock - quantity, version=DirectProduct.version + 1)
        )
        if cast(CursorResult[Any], reserved).rowcount != 1:
            await self.session.rollback()
            raise DirectCommerceError("insufficient_stock", "商品库存不足", 409)
        now = utcnow()
        profile = entry.profile
        row = DirectOrder(
            tenant_id=entry.binding.tenant_id,
            mini_program_id=product.mini_program_id,
            store_id=entry.store.id,
            product_id=product.id,
            platform_mini_program_id=entry.program.id,
            store_binding_id=entry.binding.id,
            platform_consumer_id=consumer.id,
            payment_profile_id=profile.id if profile else None,
            store_code_snapshot=store_code,
            payment_mode=profile.mode if profile else None,
            mchid_snapshot=profile.mchid if profile else None,
            sub_mchid_snapshot=profile.sub_mchid if profile else None,
            order_no=now.strftime("PF%Y%m%d%H%M%S") + secrets.token_hex(5).upper(),
            idempotency_key=idempotency_key,
            product_name=product.name,
            quantity=quantity,
            unit_amount=product.sale_price,
            total_amount=product.sale_price * quantity,
            expires_at=now + timedelta(minutes=15),
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise DirectCommerceError("order_conflict", "订单重复，请刷新", 409) from error
        await self.session.refresh(row)
        return row

    async def order(
        self, store_code: str, consumer_id: str, order_id: str
    ) -> DirectOrder:
        entry = await self.resolve(store_code)
        row = await self.session.scalar(
            select(DirectOrder).where(
                DirectOrder.id == order_id,
                DirectOrder.tenant_id == entry.binding.tenant_id,
                DirectOrder.store_binding_id == entry.binding.id,
                DirectOrder.platform_consumer_id == consumer_id,
            )
        )
        if row is None:
            raise DirectCommerceError("order_not_found", "订单不存在", 404)
        return row

    async def pay_order(
        self,
        store_code: str,
        consumer: PlatformConsumerIdentity,
        order_id: str,
        description: str | None,
    ) -> tuple[DirectOrder, dict[str, str], str | None]:
        entry = await self.resolve(store_code)
        await self.require_tradable(entry)
        order = await self.order(store_code, consumer.id, order_id)
        if order.status == "paid":
            voucher = await self._voucher_for_order(order.id)
            code = self._decrypt_code(voucher) if voucher else None
            return order, {}, code
        if order.status != "payment_pending":
            raise DirectCommerceError("order_not_payable", "订单当前不能支付", 409)
        if _aware(order.expires_at) <= utcnow():
            order.status = "expired"
            await self._restore_stock(order)
            await self.session.commit()
            raise DirectCommerceError("order_expired", "订单已超时，请重新下单", 409)
        if entry.profile is None:
            raise DirectCommerceError("payment_profile_required", "门店支付档案未配置", 409)
        connection = await self._profile_connection(entry.profile)
        route = self._payment_route(entry, connection)
        if connection.mode == ConnectionMode.MOCK.value:
            voucher_code = await self._mark_paid(
                order, transaction_id="MOCK" + secrets.token_hex(10).upper()
            )
            await self.session.commit()
            await self.session.refresh(order)
            return order, {"mock": "true"}, voucher_code
        bundle = self._secrets(connection)
        try:
            payment = await WeChatPayClient(self.http_client).create_jsapi_order(
                app_id=route.app_id,
                merchant_id=route.merchant_id,
                merchant_serial_no=self._required(bundle, "merchant_serial_no", "商户证书序列号"),
                merchant_private_key_pem=self._required(
                    bundle, "merchant_private_key_pem", "微信支付商户私钥"
                ),
                wechatpay_public_key_pem=self._required(
                    bundle, "wechatpay_public_key_pem", "微信支付公钥"
                ),
                order_no=order.order_no,
                description=description or order.product_name,
                amount=order.total_amount,
                openid=self._openid(consumer),
                notify_url=self._required(bundle, "notify_url", "支付通知地址"),
                sub_mchid=route.sub_mchid,
                sp_mchid=route.sp_mchid,
            )
        except WeChatPayError as error:
            raise DirectCommerceError(error.code, error.message, error.status_code) from error
        order.prepay_id = payment.prepay_id
        await self.session.commit()
        await self.session.refresh(order)
        return order, payment.parameters, None

    def _payment_route(
        self, entry: StoreEntry, connection: WeChatConnection
    ) -> PaymentRoute:
        profile = entry.profile
        assert profile is not None
        if profile.mode == "partner":
            if not profile.sp_mchid or not profile.sub_mchid:
                raise DirectCommerceError(
                    "payment_profile_not_ready", "服务商子商户配置缺失", 409
                )
            if connection.merchant_id and connection.merchant_id != profile.sp_mchid:
                raise DirectCommerceError(
                    "payment_profile_mismatch", "支付连接服务商号与门店支付档案不一致", 409
                )
            return PaymentRoute(
                merchant_id=profile.sp_mchid,
                app_id=self._required_value(entry.program.app_id, "平台小程序 AppID"),
                sub_mchid=profile.sub_mchid,
                sp_mchid=profile.sp_mchid,
            )
        if not profile.mchid:
            raise DirectCommerceError("payment_profile_not_ready", "门店普通商户号缺失", 409)
        if connection.merchant_id and connection.merchant_id != profile.mchid:
            raise DirectCommerceError(
                "payment_profile_mismatch", "支付连接商户号与门店支付档案不一致", 409
            )
        if (
            connection.app_id
            and entry.program.app_id
            and connection.app_id != entry.program.app_id
        ):
            raise DirectCommerceError(
                "payment_appid_mismatch", "支付连接 AppID 与平台小程序未绑定", 409
            )
        return PaymentRoute(
            merchant_id=profile.mchid,
            app_id=self._required_value(entry.program.app_id, "平台小程序 AppID"),
            sub_mchid=None,
            sp_mchid=None,
        )

    async def handle_payment_notification(
        self, payment_profile_id: str, headers: dict[str, str], body: bytes
    ) -> None:
        profile = await self.session.scalar(
            select(MerchantPaymentProfile).where(
                MerchantPaymentProfile.id == payment_profile_id
            )
        )
        if profile is None:
            raise DirectCommerceError("payment_profile_not_found", "门店支付档案不存在", 404)
        connection = await self._profile_connection(profile)
        if connection.mode != ConnectionMode.LIVE.value:
            raise DirectCommerceError(
                "live_connection_required", "模拟连接不接收支付通知", 409
            )
        bundle = self._secrets(connection)
        public_key = self._required(bundle, "wechatpay_public_key_pem", "微信支付公钥")
        try:
            verify_notification(headers, body, public_key)
            payload = cast(dict[str, Any], json.loads(body))
            resource = payload.get("resource")
            if not isinstance(resource, dict):
                raise WeChatPayError("wechatpay_resource_missing", "支付通知缺少资源", 400)
            transaction = decrypt_notification_resource(
                resource, self._required(bundle, "api_v3_key", "APIv3 密钥")
            )
        except (ValueError, WeChatPayError) as error:
            if isinstance(error, WeChatPayError):
                raise DirectCommerceError(error.code, error.message, error.status_code) from error
            raise DirectCommerceError(
                "wechatpay_notification_invalid", "支付通知格式无效", 400
            ) from error
        if transaction.get("trade_state") != "SUCCESS":
            out_refund_no = transaction.get("out_refund_no")
            if isinstance(out_refund_no, str) and out_refund_no:
                await self._handle_refund_notification(transaction, profile, out_refund_no)
            return
        order_no = transaction.get("out_trade_no")
        order = await self.session.scalar(
            select(DirectOrder)
            .where(
                DirectOrder.order_no == order_no,
                DirectOrder.payment_profile_id == profile.id,
            )
            .with_for_update()
        )
        if order is None:
            raise DirectCommerceError("order_not_found", "支付通知对应订单不存在", 404)
        program = await self.session.scalar(
            select(PlatformMiniProgram).where(
                PlatformMiniProgram.id == order.platform_mini_program_id
            )
        )
        tx_appid = transaction.get("appid") or transaction.get("sp_appid")
        tx_mchid = transaction.get("mchid") or transaction.get("sp_mchid")
        tx_sub_mchid = transaction.get("sub_mchid")
        amount = transaction.get("amount")
        total = amount.get("total") if isinstance(amount, dict) else None
        if (
            program is None
            or tx_appid != program.app_id
            or tx_mchid != order.mchid_snapshot
            or tx_sub_mchid != order.sub_mchid_snapshot
            or total != order.total_amount
        ):
            raise DirectCommerceError("payment_identity_mismatch", "支付通知身份或金额不匹配", 400)
        if order.status == "paid":
            return
        transaction_id = transaction.get("transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id:
            raise DirectCommerceError("transaction_id_missing", "支付通知缺少交易号", 400)
        await self._mark_paid(order, transaction_id=transaction_id)
        await self.session.commit()

    async def consumer_voucher(
        self, store_code: str, consumer_id: str, order_id: str
    ) -> tuple[DirectVoucher, str]:
        order = await self.order(store_code, consumer_id, order_id)
        if order.status != "paid":
            raise DirectCommerceError("paid_order_required", "订单尚未支付", 409)
        voucher = await self._voucher_for_order(order.id)
        if voucher is None:
            raise DirectCommerceError("voucher_not_found", "订单券码尚未生成", 404)
        return voucher, self._decrypt_code(voucher)

    async def create_appointment(
        self,
        store_code: str,
        consumer: PlatformConsumerIdentity,
        order_id: str,
        values: dict[str, Any],
    ) -> DirectAppointment:
        order = await self.order(store_code, consumer.id, order_id)
        if order.status != "paid":
            raise DirectCommerceError("paid_order_required", "订单支付后才能预约", 409)
        starts_at = values["starts_at"]
        if _aware(starts_at) <= utcnow():
            raise DirectCommerceError("appointment_in_past", "预约时间必须晚于当前时间")
        if await self.session.scalar(
            select(DirectAppointment.id).where(DirectAppointment.order_id == order.id)
        ):
            raise DirectCommerceError("appointment_exists", "该订单已经预约", 409)
        phone = str(values.pop("contact_phone"))
        row = DirectAppointment(
            tenant_id=order.tenant_id,
            order_id=order.id,
            store_id=order.store_id,
            contact_phone_ciphertext=encrypt_secret_bundle(
                {"phone": phone}, self.settings.encryption_key
            ),
            contact_phone_masked=_masked_phone(phone),
            **values,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def _handle_refund_notification(
        self,
        transaction: dict[str, Any],
        profile: MerchantPaymentProfile,
        out_refund_no: str,
    ) -> None:
        refund = await self.session.scalar(
            select(DirectRefund).where(
                DirectRefund.refund_no == out_refund_no,
                DirectRefund.payment_profile_id == profile.id,
            )
        )
        if refund is None:
            raise DirectCommerceError("refund_not_found", "退款通知对应退款单不存在", 404)
        order = await self.session.scalar(
            select(DirectOrder).where(DirectOrder.id == refund.order_id).with_for_update()
        )
        if order is None:
            raise DirectCommerceError("order_not_found", "退款通知对应订单不存在", 404)
        refund_id = transaction.get("refund_id")
        if isinstance(refund_id, str) and refund_id and not refund.wechat_refund_id:
            refund.wechat_refund_id = refund_id
        refund_status = transaction.get("refund_status")
        if refund_status == "SUCCESS":
            if refund.status != "success":
                await DirectCommerceService(self.session, self.settings)._apply_refund(
                    order, refund
                )
                refund.status = "success"
                refund.version += 1
        elif refund_status == "CLOSED":
            refund.status = "failed"
            refund.version += 1
        await self.session.commit()

    async def _openid_from_code(
        self, program: PlatformMiniProgram, connection: WeChatConnection, code: str
    ) -> str:
        if connection.mode == ConnectionMode.MOCK.value:
            return "mock_" + _hash(code)[:28]
        bundle = self._secrets(connection)
        app_secret = self._required(bundle, "app_secret", "平台小程序 AppSecret")
        try:
            client = self.http_client or httpx.AsyncClient(timeout=15.0)
            response = await client.get(
                self.settings.wechat_api_base_url + "/sns/jscode2session",
                params={
                    "appid": program.app_id,
                    "secret": app_secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            if self.http_client is None:
                await client.aclose()
        except httpx.HTTPError as error:
            raise DirectCommerceError(
                "wechat_login_unavailable", "微信登录暂不可用", 502
            ) from error
        value = response.json()
        openid = value.get("openid") if isinstance(value, dict) else None
        if response.status_code >= 400 or not isinstance(openid, str) or not openid:
            raise DirectCommerceError("wechat_login_rejected", "微信登录凭证无效", 401)
        return openid

    async def _program_connection(self, program: PlatformMiniProgram) -> WeChatConnection:
        if not program.connection_id:
            raise DirectCommerceError(
                "platform_connection_required", "平台小程序交易连接未配置", 409
            )
        connection = await self.session.scalar(
            select(WeChatConnection).where(
                WeChatConnection.id == program.connection_id,
                WeChatConnection.capability == Capability.MINI_PROGRAM_COMMERCE.value,
            )
        )
        if connection is None:
            raise DirectCommerceError(
                "platform_connection_invalid", "平台小程序交易连接无效", 409
            )
        return connection

    async def _profile_connection(self, profile: MerchantPaymentProfile) -> WeChatConnection:
        if not profile.connection_id:
            raise DirectCommerceError("payment_connection_required", "门店支付连接未配置", 409)
        connection = await self.session.scalar(
            select(WeChatConnection).where(WeChatConnection.id == profile.connection_id)
        )
        if connection is None:
            raise DirectCommerceError("payment_connection_invalid", "门店支付连接无效", 409)
        return connection

    def _secrets(self, connection: WeChatConnection) -> dict[str, Any]:
        if not connection.encrypted_secrets:
            raise DirectCommerceError("credentials_missing", "小程序交易凭据尚未配置", 409)
        try:
            return decrypt_secret_bundle(
                connection.encrypted_secrets, self.settings.encryption_key
            )
        except ValueError as error:
            raise DirectCommerceError(
                "credentials_invalid", "小程序交易凭据无法解密", 500
            ) from error

    @staticmethod
    def _required(bundle: dict[str, Any], key: str, label: str) -> str:
        return PlatformCommerceService._required_value(bundle.get(key), label)

    @staticmethod
    def _required_value(value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DirectCommerceError(
                "payment_configuration_incomplete", f"缺少{label}", 409
            )
        return value

    def _openid(self, consumer: PlatformConsumerIdentity) -> str:
        try:
            value = decrypt_secret_bundle(
                consumer.openid_ciphertext, self.settings.encryption_key
            )
        except ValueError as error:
            raise DirectCommerceError(
                "consumer_identity_invalid", "顾客身份数据无法解密", 500
            ) from error
        return self._required(value, "openid", "顾客 openid")

    async def _mark_paid(self, order: DirectOrder, transaction_id: str) -> str:
        order.status = "paid"
        order.paid_amount = order.total_amount
        order.transaction_id = transaction_id
        order.paid_at = utcnow()
        await self.session.execute(
            update(DirectProduct)
            .where(DirectProduct.id == order.product_id)
            .values(sold_count=DirectProduct.sold_count + order.quantity)
        )
        voucher = await self._voucher_for_order(order.id)
        if voucher is not None:
            return self._decrypt_code(voucher)
        code = "".join(secrets.choice("0123456789") for _ in range(12))
        self.session.add(
            DirectVoucher(
                tenant_id=order.tenant_id,
                order_id=order.id,
                code_hash=_hash(code),
                code_ciphertext=encrypt_secret_bundle(
                    {"code": code}, self.settings.encryption_key
                ),
                code_masked=code[:4] + "****" + code[-4:],
                valid_until=utcnow() + timedelta(days=365),
            )
        )
        return code

    async def _restore_stock(self, order: DirectOrder) -> None:
        await self.session.execute(
            update(DirectProduct)
            .where(DirectProduct.id == order.product_id)
            .values(stock=DirectProduct.stock + order.quantity)
        )

    async def _voucher_for_order(self, order_id: str) -> DirectVoucher | None:
        return (
            await self.session.execute(
                select(DirectVoucher).where(DirectVoucher.order_id == order_id)
            )
        ).scalar_one_or_none()

    def _decrypt_code(self, voucher: DirectVoucher) -> str:
        try:
            value = decrypt_secret_bundle(
                voucher.code_ciphertext, self.settings.encryption_key
            )
        except ValueError as error:
            raise DirectCommerceError(
                "voucher_data_invalid", "券码数据无法解密", 500
            ) from error
        return self._required(value, "code", "券码")


__all__ = ["PaymentRoute", "PlatformCommerceService", "StoreEntry"]
