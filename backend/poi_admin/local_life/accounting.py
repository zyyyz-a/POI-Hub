"""Funds-flow and voucher-bill mirrors with deterministic reconciliation summaries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, GatewayTerminalError, LocalLifeGateway
from poi_admin.connections.service import ConnectionService
from poi_admin.core.config import Settings
from poi_admin.operations.models import IntegrationOperation
from poi_admin.operations.service import OperationService
from poi_admin.operations.worker import Handler

from .models import FundsFlow, VoucherBill

ACCOUNTING_SYNC_COMMAND = "local_life.accounting.sync"


class AccountingServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _safe_entry(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "type",
        "entry_type",
        "bill_type",
        "amount",
        "currency",
        "occurred_at",
        "created_at",
        "updated_at",
        "order_id",
        "voucher_id",
        "status",
    }
    return {
        str(key): value
        for key, value in raw.items()
        if key in allowed and not isinstance(value, (dict, list))
    }


class AccountingService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings

    async def sync_accounting(
        self, tenant_id: str, connection_id: str, idempotency_key: str
    ) -> IntegrationOperation:
        connection = (
            await self.session.execute(
                select(WeChatConnection).where(
                    WeChatConnection.tenant_id == tenant_id,
                    WeChatConnection.id == connection_id,
                    WeChatConnection.capability == Capability.LOCAL_LIFE.value,
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            raise AccountingServiceError("connection_not_found", "连接不存在", 404)
        return await OperationService(self.session).enqueue(
            tenant_id,
            ACCOUNTING_SYNC_COMMAND,
            idempotency_key,
            {"connection_id": connection_id},
            connection_id=connection_id,
            resource_ref=f"local_accounting:{connection_id}",
        )

    async def list_funds(self, tenant_id: str) -> list[FundsFlow]:
        return list(
            (
                await self.session.execute(
                    select(FundsFlow)
                    .where(FundsFlow.tenant_id == tenant_id)
                    .order_by(FundsFlow.occurred_at.desc(), FundsFlow.id)
                )
            )
            .scalars()
            .all()
        )

    async def list_bills(self, tenant_id: str) -> list[VoucherBill]:
        return list(
            (
                await self.session.execute(
                    select(VoucherBill)
                    .where(VoucherBill.tenant_id == tenant_id)
                    .order_by(VoucherBill.occurred_at.desc(), VoucherBill.id)
                )
            )
            .scalars()
            .all()
        )

    async def reconciliation_summary(self, tenant_id: str) -> dict[str, Any]:
        funds = await self.list_funds(tenant_id)
        bills = await self.list_bills(tenant_id)
        fund_total = sum(item.amount for item in funds)
        bill_total = sum(item.amount for item in bills)
        fund_by_key = {item.external_entry_id: item.amount for item in funds}
        bill_by_key = {item.external_bill_id: item.amount for item in bills}
        differences: list[dict[str, Any]] = []
        for key in sorted(set(fund_by_key) | set(bill_by_key)):
            fund_amount = fund_by_key.get(key)
            bill_amount = bill_by_key.get(key)
            if fund_amount != bill_amount:
                differences.append(
                    {
                        "external_id": key,
                        "fund_amount": fund_amount,
                        "bill_amount": bill_amount,
                        "difference": (fund_amount or 0) - (bill_amount or 0),
                    }
                )
        return {
            "fund_count": len(funds),
            "bill_count": len(bills),
            "fund_total": fund_total,
            "bill_total": bill_total,
            "difference": fund_total - bill_total,
            "difference_count": len(differences),
            "differences": differences,
            "funds": [
                {
                    "id": item.id,
                    "external_id": item.external_entry_id,
                    "entry_type": item.entry_type,
                    "amount": item.amount,
                    "currency": item.currency,
                    "occurred_at": item.occurred_at,
                }
                for item in funds
            ],
            "bills": [
                {
                    "id": item.id,
                    "external_id": item.external_bill_id,
                    "entry_type": item.bill_type,
                    "amount": item.amount,
                    "currency": item.currency,
                    "occurred_at": item.occurred_at,
                }
                for item in bills
            ],
        }


def accounting_operation_handlers(
    session: AsyncSession,
    settings: Settings | None = None,
    *,
    gateway_override: LocalLifeGateway | None = None,
) -> dict[str, Handler]:
    service = AccountingService(session, settings=settings)

    async def gateway_for(operation: IntegrationOperation) -> LocalLifeGateway:
        connection_id = operation.payload.get("connection_id")
        if not isinstance(connection_id, str):
            raise GatewayTerminalError("对账操作参数无效", code="invalid_operation_payload")
        if gateway_override is not None:
            return gateway_override
        if settings is None:
            raise GatewayTerminalError(
                "gateway settings are missing", code="gateway_not_configured"
            )
        connection = (
            await session.execute(
                select(WeChatConnection).where(
                    WeChatConnection.tenant_id == operation.tenant_id,
                    WeChatConnection.id == connection_id,
                    WeChatConnection.capability == Capability.LOCAL_LIFE.value,
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            raise GatewayTerminalError("连接不存在", code="connection_not_found")
        return cast(
            LocalLifeGateway,
            await ConnectionService(session, settings).gateway(operation.tenant_id, connection.id),
        )

    async def sync(operation: IntegrationOperation) -> dict[str, Any]:
        connection_id = operation.payload.get("connection_id")
        if not isinstance(connection_id, str):
            raise GatewayTerminalError("对账操作参数无效", code="invalid_operation_payload")
        gateway = await gateway_for(operation)
        funds, _ = await gateway.list_funds()
        bills, _ = await gateway.list_bills()
        for raw in funds:
            if not isinstance(raw, dict):
                continue
            external_id = str(raw.get("id", raw.get("external_id", ""))).strip()
            if not external_id:
                continue
            entry = (
                await session.execute(
                    select(FundsFlow).where(
                        FundsFlow.tenant_id == operation.tenant_id,
                        FundsFlow.connection_id == connection_id,
                        FundsFlow.external_entry_id == external_id,
                    )
                )
            ).scalar_one_or_none()
            if entry is None:
                entry = FundsFlow(
                    tenant_id=operation.tenant_id,
                    connection_id=connection_id,
                    external_entry_id=external_id,
                )
                session.add(entry)
            entry.entry_type = (
                str(raw.get("entry_type", raw.get("type")))
                if raw.get("entry_type", raw.get("type")) is not None
                else None
            )
            entry.amount = _as_int(raw.get("amount"))
            entry.currency = str(raw.get("currency", "CNY"))
            entry.occurred_at = _as_datetime(raw.get("occurred_at", raw.get("created_at")))
            entry.raw_summary = _safe_entry(raw)
        for raw in bills:
            if not isinstance(raw, dict):
                continue
            external_id = str(raw.get("id", raw.get("external_id", ""))).strip()
            if not external_id:
                continue
            bill = (
                await session.execute(
                    select(VoucherBill).where(
                        VoucherBill.tenant_id == operation.tenant_id,
                        VoucherBill.connection_id == connection_id,
                        VoucherBill.external_bill_id == external_id,
                    )
                )
            ).scalar_one_or_none()
            if bill is None:
                bill = VoucherBill(
                    tenant_id=operation.tenant_id,
                    connection_id=connection_id,
                    external_bill_id=external_id,
                )
                session.add(bill)
            bill.bill_type = (
                str(raw.get("bill_type", raw.get("type")))
                if raw.get("bill_type", raw.get("type")) is not None
                else None
            )
            bill.amount = _as_int(raw.get("amount"))
            bill.currency = str(raw.get("currency", "CNY"))
            bill.occurred_at = _as_datetime(raw.get("occurred_at", raw.get("created_at")))
            bill.raw_summary = _safe_entry(raw)
        await session.commit()
        summary = await service.reconciliation_summary(operation.tenant_id)
        return cast(dict[str, Any], {"fund_count": len(funds), "bill_count": len(bills), **summary})

    return {ACCOUNTING_SYNC_COMMAND: sync}


__all__ = [
    "ACCOUNTING_SYNC_COMMAND",
    "AccountingService",
    "AccountingServiceError",
    "accounting_operation_handlers",
]
