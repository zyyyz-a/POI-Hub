"""Application rules for merchant-owned mini-program sales and redemption."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.crypto import decrypt_secret_bundle, encrypt_secret_bundle
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.core.config import Settings
from poi_admin.onboarding.models import MerchantMiniProgram, PositionServiceMount
from poi_admin.stores.models import Store

from .models import (
    ConsumerIdentity,
    ConsumerSession,
    DirectAppointment,
    DirectOrder,
    DirectProduct,
    DirectVoucher,
    utcnow,
)
from .wechat_pay import (
    WeChatPayClient,
    WeChatPayError,
    decrypt_notification_resource,
    verify_notification,
)


class DirectCommerceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _masked_phone(value: str) -> str:
    return value[:3] + "****" + value[-4:] if len(value) >= 7 else "****"


class DirectCommerceService:
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

    async def list_products(self, tenant_id: str) -> list[DirectProduct]:
        rows = await self.session.execute(
            select(DirectProduct)
            .where(DirectProduct.tenant_id == tenant_id)
            .order_by(DirectProduct.updated_at.desc(), DirectProduct.id)
        )
        return list(rows.scalars().all())

    async def public_products(self, mini_program_id: str) -> list[DirectProduct]:
        await self._ready_app(mini_program_id)
        rows = await self.session.execute(
            select(DirectProduct)
            .where(
                DirectProduct.mini_program_id == mini_program_id,
                DirectProduct.status == "listed",
                DirectProduct.stock > 0,
            )
            .order_by(DirectProduct.created_at.desc())
        )
        return list(rows.scalars().all())

    async def get_product(self, tenant_id: str, product_id: str) -> DirectProduct:
        row = (
            await self.session.execute(
                select(DirectProduct).where(
                    DirectProduct.tenant_id == tenant_id, DirectProduct.id == product_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise DirectCommerceError("direct_product_not_found", "小程序商品不存在", 404)
        return row

    async def create_product(self, tenant_id: str, values: dict[str, Any]) -> DirectProduct:
        app = await self._tenant_app(tenant_id, str(values["mini_program_id"]))
        store = await self.session.scalar(
            select(Store).where(Store.tenant_id == tenant_id, Store.id == values["store_id"])
        )
        if store is None:
            raise DirectCommerceError("store_not_found", "门店不存在", 404)
        if values["market_price"] < values["sale_price"]:
            raise DirectCommerceError("invalid_price", "划线价不能低于销售价")
        product_values = dict(values)
        product_values.pop("mini_program_id", None)
        row = DirectProduct(tenant_id=tenant_id, mini_program_id=app.id, **product_values)
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise DirectCommerceError("direct_product_exists", "商家商品编号已存在", 409) from error
        await self.session.refresh(row)
        return row

    async def update_product(
        self, tenant_id: str, product_id: str, version: int, changes: dict[str, Any]
    ) -> DirectProduct:
        row = await self.get_product(tenant_id, product_id)
        if row.version != version:
            raise DirectCommerceError("version_conflict", "商品已被他人修改，请刷新", 409)
        if changes.get("status") == "listed":
            await self._ready_app(row.mini_program_id)
            if (changes.get("stock", row.stock) or 0) <= 0:
                raise DirectCommerceError("stock_required", "上架商品库存必须大于零")
        for key, value in changes.items():
            setattr(row, key, value)
        if row.market_price < row.sale_price:
            raise DirectCommerceError("invalid_price", "划线价不能低于销售价")
        row.version += 1
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def consumer_login(self, mini_program_id: str, code: str) -> tuple[str, datetime]:
        app = await self._ready_app(mini_program_id)
        connection = await self._commerce_connection(app)
        openid: str
        if connection.mode == ConnectionMode.MOCK.value:
            openid = "mock_" + _hash(code)[:28]
        else:
            bundle = self._secrets(connection)
            app_secret = self._required(bundle, "app_secret", "小程序 AppSecret")
            try:
                client = self.http_client or httpx.AsyncClient(timeout=15.0)
                response = await client.get(
                    self.settings.wechat_api_base_url + "/sns/jscode2session",
                    params={
                        "appid": app.app_id,
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
            openid_value = value.get("openid") if isinstance(value, dict) else None
            if response.status_code >= 400 or not isinstance(openid_value, str) or not openid_value:
                raise DirectCommerceError("wechat_login_rejected", "微信登录凭证无效", 401)
            openid = openid_value
        openid_hash = _hash(openid)
        identity = (
            await self.session.execute(
                select(ConsumerIdentity).where(
                    ConsumerIdentity.tenant_id == app.tenant_id,
                    ConsumerIdentity.mini_program_id == app.id,
                    ConsumerIdentity.openid_hash == openid_hash,
                )
            )
        ).scalar_one_or_none()
        if identity is None:
            identity = ConsumerIdentity(
                tenant_id=app.tenant_id,
                mini_program_id=app.id,
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
            ConsumerSession(
                identity_id=identity.id, token_hash=_hash(access_token), expires_at=expires_at
            )
        )
        await self.session.commit()
        return access_token, expires_at

    async def consumer(self, access_token: str, mini_program_id: str) -> ConsumerIdentity:
        row = (
            await self.session.execute(
                select(ConsumerIdentity)
                .join(ConsumerSession, ConsumerSession.identity_id == ConsumerIdentity.id)
                .where(
                    ConsumerSession.token_hash == _hash(access_token),
                    ConsumerSession.revoked_at.is_(None),
                    ConsumerSession.expires_at > utcnow(),
                    ConsumerIdentity.mini_program_id == mini_program_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise DirectCommerceError("consumer_authentication_required", "顾客登录已失效", 401)
        return row

    async def create_order(
        self,
        mini_program_id: str,
        consumer: ConsumerIdentity,
        product_id: str,
        quantity: int,
        idempotency_key: str,
    ) -> DirectOrder:
        app = await self._ready_app(mini_program_id)
        existing = (
            await self.session.execute(
                select(DirectOrder).where(
                    DirectOrder.tenant_id == app.tenant_id,
                    DirectOrder.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.consumer_id != consumer.id or existing.product_id != product_id:
                raise DirectCommerceError("idempotency_conflict", "幂等键已用于其他订单", 409)
            return existing
        product = await self.get_product(app.tenant_id, product_id)
        if product.mini_program_id != app.id or product.status != "listed":
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
        row = DirectOrder(
            tenant_id=app.tenant_id,
            mini_program_id=app.id,
            store_id=product.store_id,
            product_id=product.id,
            consumer_id=consumer.id,
            order_no=now.strftime("MP%Y%m%d%H%M%S") + secrets.token_hex(5).upper(),
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

    async def consumer_order(
        self, mini_program_id: str, consumer_id: str, order_id: str
    ) -> DirectOrder:
        row = (
            await self.session.execute(
                select(DirectOrder).where(
                    DirectOrder.mini_program_id == mini_program_id,
                    DirectOrder.consumer_id == consumer_id,
                    DirectOrder.id == order_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise DirectCommerceError("order_not_found", "订单不存在", 404)
        return row

    async def list_orders(self, tenant_id: str) -> list[DirectOrder]:
        rows = await self.session.execute(
            select(DirectOrder)
            .where(DirectOrder.tenant_id == tenant_id)
            .order_by(DirectOrder.created_at.desc())
        )
        return list(rows.scalars().all())

    async def pay_order(
        self,
        mini_program_id: str,
        consumer: ConsumerIdentity,
        order_id: str,
        description: str | None,
    ) -> tuple[DirectOrder, dict[str, str], str | None]:
        order = await self.consumer_order(mini_program_id, consumer.id, order_id)
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
        app = await self._ready_app(mini_program_id)
        connection = await self._commerce_connection(app)
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
                app_id=self._required_value(app.app_id, "小程序 AppID"),
                merchant_id=self._required_value(connection.merchant_id, "微信支付商户号"),
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
            )
        except WeChatPayError as error:
            raise DirectCommerceError(error.code, error.message, error.status_code) from error
        order.prepay_id = payment.prepay_id
        await self.session.commit()
        await self.session.refresh(order)
        return order, payment.parameters, None

    async def handle_payment_notification(
        self, mini_program_id: str, headers: dict[str, str], body: bytes
    ) -> None:
        app = await self._tenantless_app(mini_program_id)
        connection = await self._commerce_connection(app)
        if connection.mode != ConnectionMode.LIVE.value:
            raise DirectCommerceError("live_connection_required", "模拟连接不接收支付通知", 409)
        bundle = self._secrets(connection)
        public_key = self._required(bundle, "wechatpay_public_key_pem", "微信支付公钥")
        try:
            verify_notification(headers, body, public_key)
            payload = cast(dict[str, Any], __import__("json").loads(body))
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
            return
        order_no = transaction.get("out_trade_no")
        order = (
            await self.session.execute(
                select(DirectOrder)
                .where(DirectOrder.mini_program_id == app.id, DirectOrder.order_no == order_no)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if order is None:
            raise DirectCommerceError("order_not_found", "支付通知对应订单不存在", 404)
        amount = transaction.get("amount")
        total = amount.get("total") if isinstance(amount, dict) else None
        if (
            transaction.get("appid") != app.app_id
            or transaction.get("mchid") != connection.merchant_id
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

    async def create_appointment(
        self,
        mini_program_id: str,
        consumer: ConsumerIdentity,
        order_id: str,
        values: dict[str, Any],
    ) -> DirectAppointment:
        order = await self.consumer_order(mini_program_id, consumer.id, order_id)
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

    async def list_appointments(self, tenant_id: str) -> list[DirectAppointment]:
        rows = await self.session.execute(
            select(DirectAppointment)
            .where(DirectAppointment.tenant_id == tenant_id)
            .order_by(DirectAppointment.starts_at)
        )
        return list(rows.scalars().all())

    async def list_vouchers(self, tenant_id: str) -> list[DirectVoucher]:
        rows = await self.session.execute(
            select(DirectVoucher)
            .where(DirectVoucher.tenant_id == tenant_id)
            .order_by(DirectVoucher.created_at.desc())
        )
        return list(rows.scalars().all())

    async def consumer_voucher(
        self, mini_program_id: str, consumer_id: str, order_id: str
    ) -> tuple[DirectVoucher, str]:
        order = await self.consumer_order(mini_program_id, consumer_id, order_id)
        if order.status != "paid":
            raise DirectCommerceError("paid_order_required", "订单尚未支付", 409)
        voucher = await self._voucher_for_order(order.id)
        if voucher is None:
            raise DirectCommerceError("voucher_not_found", "订单券码尚未生成", 404)
        return voucher, self._decrypt_code(voucher)

    async def consume_voucher(
        self, tenant_id: str, code: str, store_id: str, actor_user_id: str
    ) -> DirectVoucher:
        store = await self.session.scalar(
            select(Store.id).where(Store.tenant_id == tenant_id, Store.id == store_id)
        )
        if store is None:
            raise DirectCommerceError("store_not_found", "核销门店不存在", 404)
        voucher = (
            await self.session.execute(
                select(DirectVoucher).where(
                    DirectVoucher.tenant_id == tenant_id, DirectVoucher.code_hash == _hash(code)
                )
            )
        ).scalar_one_or_none()
        if voucher is None:
            raise DirectCommerceError("voucher_not_found", "券码不存在", 404)
        result = await self.session.execute(
            update(DirectVoucher)
            .where(
                DirectVoucher.id == voucher.id,
                DirectVoucher.state == "available",
                DirectVoucher.valid_until > utcnow(),
            )
            .values(
                state="consumed",
                consumed_at=utcnow(),
                consume_store_id=store_id,
                consumed_by_user_id=actor_user_id,
                version=DirectVoucher.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            await self.session.rollback()
            raise DirectCommerceError("voucher_not_consumable", "券码已核销、已失效或已过期", 409)
        await self.session.commit()
        return await self._voucher(tenant_id, voucher.id)

    async def revoke_voucher(self, tenant_id: str, voucher_id: str, version: int) -> DirectVoucher:
        voucher = await self._voucher(tenant_id, voucher_id)
        if voucher.version != version:
            raise DirectCommerceError("version_conflict", "券码已被他人处理，请刷新", 409)
        if voucher.state != "consumed":
            raise DirectCommerceError("voucher_not_revokable", "只有已核销券可以撤销核销", 409)
        voucher.state = "available"
        voucher.revoked_at = utcnow()
        voucher.consumed_at = None
        voucher.consume_store_id = None
        voucher.consumed_by_user_id = None
        voucher.version += 1
        await self.session.commit()
        await self.session.refresh(voucher)
        return voucher

    async def _ready_app(self, mini_program_id: str) -> MerchantMiniProgram:
        app = await self._tenantless_app(mini_program_id)
        missing = []
        if app.status != "active":
            missing.append("小程序未启用")
        if not app.payment_owner_verified:
            missing.append("商户号归属未核验")
        if not app.callback_configured:
            missing.append("支付回调未配置")
        mounted = await self.session.scalar(
            select(PositionServiceMount.id).where(
                PositionServiceMount.tenant_id == app.tenant_id,
                PositionServiceMount.mini_program_id == app.id,
                PositionServiceMount.status == "mounted",
            )
        )
        if mounted is None:
            missing.append("微信位置服务未挂载")
        if missing:
            raise DirectCommerceError(
                "mini_program_not_ready", "暂不能营业：" + "、".join(missing), 409
            )
        return app

    async def _tenantless_app(self, mini_program_id: str) -> MerchantMiniProgram:
        row = await self.session.scalar(
            select(MerchantMiniProgram).where(MerchantMiniProgram.id == mini_program_id)
        )
        if row is None:
            raise DirectCommerceError("mini_program_not_found", "小程序不存在", 404)
        return row

    async def _tenant_app(self, tenant_id: str, mini_program_id: str) -> MerchantMiniProgram:
        row = await self.session.scalar(
            select(MerchantMiniProgram).where(
                MerchantMiniProgram.tenant_id == tenant_id,
                MerchantMiniProgram.id == mini_program_id,
            )
        )
        if row is None:
            raise DirectCommerceError("mini_program_not_found", "小程序不存在", 404)
        return row

    async def _commerce_connection(self, app: MerchantMiniProgram) -> WeChatConnection:
        if not app.connection_id:
            raise DirectCommerceError("commerce_connection_required", "小程序交易连接未配置", 409)
        connection = await self.session.scalar(
            select(WeChatConnection).where(
                WeChatConnection.tenant_id == app.tenant_id,
                WeChatConnection.id == app.connection_id,
                WeChatConnection.capability == Capability.MINI_PROGRAM_COMMERCE.value,
            )
        )
        if connection is None:
            raise DirectCommerceError("commerce_connection_invalid", "小程序交易连接无效", 409)
        return connection

    def _secrets(self, connection: WeChatConnection) -> dict[str, Any]:
        if not connection.encrypted_secrets:
            raise DirectCommerceError("credentials_missing", "小程序交易凭据尚未配置", 409)
        try:
            return decrypt_secret_bundle(connection.encrypted_secrets, self.settings.encryption_key)
        except ValueError as error:
            raise DirectCommerceError(
                "credentials_invalid", "小程序交易凭据无法解密", 500
            ) from error

    @staticmethod
    def _required(bundle: dict[str, Any], key: str, label: str) -> str:
        value = bundle.get(key)
        return DirectCommerceService._required_value(value, label)

    @staticmethod
    def _required_value(value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DirectCommerceError("payment_configuration_incomplete", f"缺少{label}", 409)
        return value

    def _openid(self, consumer: ConsumerIdentity) -> str:
        try:
            value = decrypt_secret_bundle(consumer.openid_ciphertext, self.settings.encryption_key)
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
                code_ciphertext=encrypt_secret_bundle({"code": code}, self.settings.encryption_key),
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

    async def _voucher(self, tenant_id: str, voucher_id: str) -> DirectVoucher:
        row = await self.session.scalar(
            select(DirectVoucher)
            .where(DirectVoucher.tenant_id == tenant_id, DirectVoucher.id == voucher_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise DirectCommerceError("voucher_not_found", "券码不存在", 404)
        return row

    def _decrypt_code(self, voucher: DirectVoucher) -> str:
        try:
            value = decrypt_secret_bundle(voucher.code_ciphertext, self.settings.encryption_key)
        except ValueError as error:
            raise DirectCommerceError("voucher_data_invalid", "券码数据无法解密", 500) from error
        return self._required(value, "code", "券码")


__all__ = ["DirectCommerceError", "DirectCommerceService"]
