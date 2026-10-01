"""Create an isolated, idempotent demo store; never reset existing business data."""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from poi_admin.audit.models import AuditLog
from poi_admin.connections.models import WeChatConnection
from poi_admin.core.config import get_settings
from poi_admin.core.database import create_database
from poi_admin.direct_commerce.models import DirectProduct, MerchantPaymentProfile
from poi_admin.identity.models import Tenant, User
from poi_admin.main import create_app
from poi_admin.onboarding.models import (
    MerchantMiniProgram,
    MiniProgramStoreBinding,
    PlatformMiniProgram,
)
from poi_admin.stores.models import Store

STORE_CODE = "demo-experience"
TENANT_SLUG = "poi-hub-demo-experience"


async def run(app_id: str) -> None:
    settings = get_settings()
    create_app(settings)  # Register all mapped models before opening the session.
    database = create_database(settings)
    try:
        async with database.session_factory() as session:
            existing = await session.scalar(
                select(MiniProgramStoreBinding).where(
                    MiniProgramStoreBinding.store_code == STORE_CODE
                )
            )
            if existing:
                tenant = await session.get(Tenant, existing.tenant_id)
                if tenant is None or tenant.slug != TENANT_SLUG:
                    raise RuntimeError("Demo store code is already owned by another tenant")
                print(json.dumps({"store_code": STORE_CODE, "created": False}))
                return

            admin = await session.scalar(
                select(User).where(User.is_platform_admin.is_(True), User.status == "active")
                .order_by(User.created_at)
            )
            if admin is None:
                raise RuntimeError("An existing active platform administrator is required")
            program_exists = await session.scalar(
                select(PlatformMiniProgram.id).where(PlatformMiniProgram.app_id == app_id)
            )
            if program_exists:
                raise RuntimeError(
                    "AppID already registered; existing platform will not be changed"
                )

            tenant = Tenant(
                name="模拟体验商户（测试数据）", slug=TENANT_SLUG,
                status="active", created_by_user_id=admin.id,
            )
            session.add(tenant)
            await session.flush()
            connection = WeChatConnection(
                tenant_id=tenant.id, capability="mini_program_commerce", mode="mock",
                mock_scenario="healthy", status="connected", app_id=app_id,
                merchant_id="MOCK-DEMO-MERCHANT",
                permission_snapshot={"simulation": True, "real_payment": False},
            )
            session.add(connection)
            await session.flush()
            actor = {"created_by_user_id": admin.id, "updated_by_user_id": admin.id}
            program = PlatformMiniProgram(
                name="模拟体验小程序（不真实扣款）", app_id=app_id,
                owner_subject="POI Hub 模拟测试", connection_id=connection.id,
                status="active", callback_configured=True, **actor,
            )
            merchant_program = MerchantMiniProgram(
                tenant_id=tenant.id, connection_id=connection.id,
                name="模拟体验店商品目录", app_id=app_id, owner_subject="模拟测试主体",
                ownership_mode="platform_owned", status="active",
                authorization_reference="mock-only:no-official-authorization",
                payment_merchant_id="MOCK-DEMO-MERCHANT", payment_owner_verified=True,
                callback_configured=True, **actor,
            )
            store = Store(
                tenant_id=tenant.id, code="DEMO-EXPERIENCE", name="模拟体验店（不真实扣款）",
                province="河南省", city="漯河市", district="源汇区",
                address="模拟地址 · 到店服务体验中心（非真实营业门店）",
                business_hours="09:00–21:00", status="active",
                intro="这是供功能测试的模拟店铺。商品、支付和券码仅用于体验，不会真实扣款。",
                service_guarantees="模拟支付 · 测试券码 · 不提供真实到店服务",
                appointment_notes="预约仅作流程体验；所有价格均为测试展示价格。",
                environment_images=[],
            )
            session.add_all([program, merchant_program, store])
            await session.flush()
            binding = MiniProgramStoreBinding(
                platform_mini_program_id=program.id, tenant_id=tenant.id, store_id=store.id,
                store_code=STORE_CODE, status="active", discoverable=True,
                entry_path=f"pages/store/index?store_code={STORE_CODE}",
                entry_scene=f"store_code={STORE_CODE}",
                evidence_reference="mock-only:no-map-mount-or-official-approval", **actor,
            )
            profile = MerchantPaymentProfile(
                tenant_id=tenant.id, store_id=store.id, connection_id=connection.id,
                mode="ordinary", mchid="MOCK-DEMO-MERCHANT", verified=True, status="active",
            )
            session.add_all([binding, profile])
            items = [
                ("DEMO-QUICK", "模拟洗剪吹体验", 990, 2900, False, 30),
                ("DEMO-BOOKING", "模拟头皮护理预约", 3900, 6900, True, 60),
                ("DEMO-PREMIUM", "模拟染烫护理套餐", 9900, 19900, True, 120),
            ]
            for code, name, price, market, appointment, minutes in items:
                session.add(DirectProduct(
                    tenant_id=tenant.id, mini_program_id=merchant_program.id, store_id=store.id,
                    merchant_product_id=code, name=name,
                    description="仅供测试，不真实扣款。可体验下单、券码和退款申请流程。"
                    + ("本套餐需要选择预约时间。" if appointment else "本套餐无需预约。"),
                    sale_price=price, market_price=market, stock=1000, status="listed",
                    appointment_required=appointment, service_minutes=minutes,
                ))
            session.add(AuditLog(
                tenant_id=tenant.id, actor_user_id=admin.id, action="demo_store.created",
                resource_type="store", resource_id=store.id,
                after_summary={"store_code": STORE_CODE, "simulation": True, "products": 3},
            ))
            await session.commit()
            print(json.dumps({
                "store_code": STORE_CODE, "store_id": store.id, "tenant_id": tenant.id,
                "created": True, "payment_mode": "mock", "products": 3,
            }))
    finally:
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", required=True)
    asyncio.run(run(parser.parse_args().app_id))
