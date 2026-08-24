from __future__ import annotations

import pytest
from sqlalchemy import select

from poi_admin.connections.crypto import encrypt_secret_bundle
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.local_life.models import LocalOrder, LocalVoucher
from poi_admin.operations.worker import OperationWorker
from poi_admin.webhooks.handlers import process_webhook_event
from poi_admin.webhooks.models import WebhookEvent
from poi_admin.webhooks.service import WebhookService


@pytest.mark.asyncio
async def test_valid_callback_is_deduplicated_by_connection_and_fingerprint(
    test_settings,
) -> None:
    from poi_admin.core.database import create_database
    from poi_admin.core.orm import Base
    from poi_admin.identity.models import Tenant
    from poi_admin.identity.service import ensure_test_identity

    database = create_database(test_settings)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.session_factory() as session:
            await ensure_test_identity(session)
            tenant = (
                await session.execute(select(Tenant).where(Tenant.slug == "demo"))
            ).scalar_one()
            connection = WeChatConnection(
                tenant_id=tenant.id,
                capability=Capability.LOCAL_LIFE.value,
                mode=ConnectionMode.LIVE.value,
                app_id="wx-test",
                encrypted_secrets=encrypt_secret_bundle(
                    {
                        "callback_token": "callback-token",
                        "encoding_aes_key": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                    },
                    test_settings.encryption_key,
                ),
            )
            session.add(connection)
            await session.commit()
            await session.refresh(connection)
            service = WebhookService(session, test_settings)
            payload = {
                "ToUserName": "wx-test",
                "FromUserName": "user",
                "MsgType": "event",
                "Event": "product_audit",
                "EventKey": "event-1",
            }

            first, duplicate = await service.ingest(connection.id, payload)
            second, was_duplicate = await service.ingest(connection.id, payload)

            assert duplicate is False
            assert was_duplicate is True
            assert first.id == second.id
            rows = (await session.execute(select(WebhookEvent))).scalars().all()
            assert len(rows) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_callback_processing_marks_event_processed(test_settings) -> None:
    from poi_admin.core.database import create_database
    from poi_admin.core.orm import Base
    from poi_admin.identity.models import Tenant
    from poi_admin.identity.service import ensure_test_identity

    database = create_database(test_settings)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.session_factory() as session:
            await ensure_test_identity(session)
            tenant = (
                await session.execute(select(Tenant).where(Tenant.slug == "demo"))
            ).scalar_one()
            connection = WeChatConnection(
                tenant_id=tenant.id,
                capability=Capability.LOCAL_LIFE.value,
                mode=ConnectionMode.LIVE.value,
                app_id="wx-test",
                encrypted_secrets=encrypt_secret_bundle(
                    {"callback_token": "token"}, test_settings.encryption_key
                ),
            )
            session.add(connection)
            await session.commit()
            await session.refresh(connection)
            event = WebhookEvent(
                tenant_id=tenant.id,
                connection_id=connection.id,
                fingerprint="f" * 64,
                event_type="product_audit",
                payload={"product_id": "missing", "status": "approved"},
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            assert await process_webhook_event(session, event) == "processed"
            assert event.processed_at is not None
            assert event.attempt_count == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_worker_processes_received_callback(test_settings) -> None:
    from poi_admin.core.database import create_database
    from poi_admin.core.orm import Base
    from poi_admin.identity.models import Tenant
    from poi_admin.identity.service import ensure_test_identity

    database = create_database(test_settings)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.session_factory() as session:
            await ensure_test_identity(session)
            tenant = (
                await session.execute(select(Tenant).where(Tenant.slug == "demo"))
            ).scalar_one()
            connection = WeChatConnection(
                tenant_id=tenant.id,
                capability=Capability.LOCAL_LIFE.value,
                mode=ConnectionMode.LIVE.value,
            )
            session.add(connection)
            await session.flush()
            session.add(
                WebhookEvent(
                    tenant_id=tenant.id,
                    connection_id=connection.id,
                    fingerprint="w" * 64,
                    event_type="payment",
                    payload={"event": "payment"},
                )
            )
            await session.commit()
            worker = OperationWorker(session, handlers={})
            assert await worker.run_once() is None
            event = (await session.execute(select(WebhookEvent))).scalar_one()
            assert event.status == "processed"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_voucher_issue_callback_encrypts_code_and_links_order(test_settings) -> None:
    from poi_admin.core.database import create_database
    from poi_admin.core.orm import Base
    from poi_admin.identity.models import Tenant
    from poi_admin.identity.service import ensure_test_identity

    database = create_database(test_settings)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.session_factory() as session:
            await ensure_test_identity(session)
            tenant = (
                await session.execute(select(Tenant).where(Tenant.slug == "demo"))
            ).scalar_one()
            connection = WeChatConnection(
                tenant_id=tenant.id,
                capability=Capability.LOCAL_LIFE.value,
                mode=ConnectionMode.LIVE.value,
            )
            session.add(connection)
            await session.commit()
            payload = {
                "Event": "channels_ec_voucher_send_succ",
                "voucher_list": [
                    {
                        "code": "SECRET-VOUCHER-1234",
                        "sku_id": "sku-1",
                        "product_id": "product-1",
                        "order_id": "order-1",
                        "openid": "openid-private",
                        "status": 1,
                    }
                ],
            }
            event, _ = await WebhookService(session, test_settings).ingest(
                connection.id, payload
            )

            assert event.payload["voucher_list"] == "[REDACTED]"
            assert "SECRET-VOUCHER-1234" not in str(event.payload)
            await process_webhook_event(session, event, test_settings)

            voucher = (await session.execute(select(LocalVoucher))).scalar_one()
            order = (await session.execute(select(LocalOrder))).scalar_one()
            assert voucher.order_id == order.id
            assert order.external_order_id == "order-1"
            assert voucher.external_voucher_id.startswith("voucher:")
            assert voucher.code_masked.endswith("1234")
            assert len(voucher.code_masked) == len("SECRET-VOUCHER-1234")
            assert voucher.code_ciphertext is not None
            assert "SECRET-VOUCHER-1234" not in voucher.code_ciphertext
            assert voucher.external_sku_id == "sku-1"
    finally:
        await database.dispose()
