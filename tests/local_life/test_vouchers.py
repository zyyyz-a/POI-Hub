from __future__ import annotations

import pytest
from sqlalchemy import select

from poi_admin.connections.mock import MockLocalLifeGateway
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import (
    Capability,
    ConnectionMode,
    GatewayTransientError,
    VoucherResult,
)
from poi_admin.identity.models import Tenant
from poi_admin.local_life.models import LocalVoucher
from poi_admin.local_life.vouchers import VoucherService, voucher_operation_handlers
from poi_admin.operations.models import OperationStatus
from poi_admin.operations.service import OperationService


@pytest.mark.asyncio
async def test_voucher_codes_are_masked_and_consumption_requires_confirmed_mapping(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        service = VoucherService(session)
        voucher = await service.upsert_remote_voucher(
            tenant.id,
            connection.id,
            VoucherResult(
                "voucher-1", "available", raw={"code": "1234567890", "sku_id": "sku-1"}
            ),
        )
        assert voucher.code_masked == "******7890"
        assert "1234567890" not in voucher.code_masked
        with pytest.raises(Exception) as failure:
            await service.enqueue_consume(
                tenant.id, voucher.id, "store-without-mapping", "consume-1"
            )
        assert getattr(failure.value, "code", None) == "store_mapping_required"


@pytest.mark.asyncio
async def test_consumption_timeout_queries_remote_state_before_retry(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        service = VoucherService(session)
        voucher = await service.upsert_remote_voucher(
            tenant.id,
            connection.id,
            VoucherResult("voucher-timeout", "available", raw={"sku_id": "sku-1"}),
        )
        operation = await OperationService(session).enqueue(
            tenant.id,
            "local_life.voucher.consume",
            "consume-timeout",
            {
                "entity_id": voucher.id,
                "out_store_id": "mapped-store",
                "consume_request_no": "consume-timeout-request",
            },
            connection_id=connection.id,
        )

        class QueryOnlyGateway(MockLocalLifeGateway):
            async def consume_voucher(
                self,
                external_id: str,
                *,
                sku_id: str,
                consume_request_no: str,
                out_store_id: str,
                consume_store_name: str | None = None,
                consume_channel: int = 2,
                reserve_no: str | None = None,
            ) -> VoucherResult:
                del (
                    external_id,
                    sku_id,
                    consume_request_no,
                    out_store_id,
                    consume_store_name,
                    consume_channel,
                    reserve_no,
                )
                raise GatewayTransientError("timeout", code="timeout")

            async def get_voucher(self, external_id: str, *, sku_id: str) -> VoucherResult:
                del sku_id
                return VoucherResult(external_id, "consumed", consume_store_id="mapped-store")

        result = await voucher_operation_handlers(
            session, gateway_override=QueryOnlyGateway(tenant.id)
        )["local_life.voucher.consume"](operation)
        assert result["reconciled"] is True
        refreshed = await session.get(LocalVoucher, voucher.id)
        assert refreshed is not None
        assert refreshed.state == "consumed"


@pytest.mark.asyncio
async def test_revoke_consumption_is_durable(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.LOCAL_LIFE.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        service = VoucherService(session)
        voucher = await service.upsert_remote_voucher(
            tenant.id,
            connection.id,
            VoucherResult(
                "voucher-revoke",
                "consumed",
                consume_store_id="mapped-store",
                raw={"sku_id": "sku-1"},
            ),
        )
        operation = await service.enqueue_revoke(tenant.id, voucher.id, "revoke-1")
        assert operation.status == OperationStatus.QUEUED.value

        class RevokeGateway(MockLocalLifeGateway):
            async def get_voucher(self, external_id: str, *, sku_id: str) -> VoucherResult:
                del sku_id
                return VoucherResult(external_id, "consumed", consume_store_id="mapped-store")

        result = await voucher_operation_handlers(
            session, gateway_override=RevokeGateway(tenant.id)
        )["local_life.voucher.revoke"](operation)
        assert result["state"] == "available"
