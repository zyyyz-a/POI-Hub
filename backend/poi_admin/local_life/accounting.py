"""Funds-flow and voucher-bill mirrors with deterministic reconciliation summaries."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, cast

import httpx
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
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value, UTC)
        except (OSError, OverflowError, ValueError):
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
        "product_id",
        "order_id",
        "consume_store_name",
        "out_store_id",
        "voucher_buy_amount",
        "voucher_pay_amount",
        "mch_favor_amount",
        "platform_favor_amount",
        "mch_settle_amount",
        "finder_settle_amount",
        "commission_fee",
        "consume_time",
        "refund_time",
        "mch_settle_time",
        "commission_fee_settle_time",
        "refund_amount",
        "after_sale_id",
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
        self,
        tenant_id: str,
        connection_id: str,
        product_id: str,
        bill_date: str,
        idempotency_key: str,
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
            {
                "connection_id": connection_id,
                "product_id": product_id,
                "bill_date": bill_date,
            },
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
        funds_by_order: defaultdict[str, int] = defaultdict(int)
        bills_by_order: defaultdict[str, int] = defaultdict(int)
        unmatched_fund_count = 0
        unmatched_bill_count = 0
        for fund in funds:
            order_id = str(fund.raw_summary.get("order_id") or "").strip()
            if order_id:
                funds_by_order[order_id] += fund.amount
            else:
                unmatched_fund_count += 1
        for bill in bills:
            order_id = str(bill.raw_summary.get("order_id") or "").strip()
            if order_id:
                bills_by_order[order_id] += bill.amount
            else:
                unmatched_bill_count += 1
        differences: list[dict[str, Any]] = []
        linked_order_ids = funds_by_order.keys() & bills_by_order.keys()
        for order_id in sorted(linked_order_ids):
            difference = funds_by_order[order_id] - bills_by_order[order_id]
            if difference:
                differences.append(
                    {
                        "external_id": order_id,
                        "fund_amount": funds_by_order[order_id],
                        "bill_amount": bills_by_order[order_id],
                        "difference": difference,
                    }
                )
        net_difference = sum(item["difference"] for item in differences)
        return {
            "fund_count": len(funds),
            "bill_count": len(bills),
            "fund_total": fund_total,
            "bill_total": bill_total,
            "difference": net_difference,
            "difference_count": len(differences),
            "differences": differences,
            "linked_order_count": len(linked_order_ids),
            "unmatched_fund_count": unmatched_fund_count
            + len(funds_by_order.keys() - bills_by_order.keys()),
            "unmatched_bill_count": unmatched_bill_count
            + len(bills_by_order.keys() - funds_by_order.keys()),
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
    http_client: httpx.AsyncClient | None = None,
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
            await ConnectionService(
                session, settings, http_client=http_client
            ).gateway(operation.tenant_id, connection.id),
        )

    async def sync(operation: IntegrationOperation) -> dict[str, Any]:
        connection_id = operation.payload.get("connection_id")
        if not isinstance(connection_id, str):
            raise GatewayTerminalError("对账操作参数无效", code="invalid_operation_payload")
        gateway = await gateway_for(operation)
        product_id = operation.payload.get("product_id")
        bill_date = operation.payload.get("bill_date")
        if not isinstance(product_id, str) or not isinstance(bill_date, str):
            raise GatewayTerminalError("对账查询维度无效", code="invalid_operation_payload")
        funds: list[dict[str, Any]] = []
        bills: list[dict[str, Any]] = []
        funds_cursor: str | None = None
        bill_cursor: str | None = None
        seen_fund_cursors: set[str] = set()
        seen_bill_cursors: set[str] = set()
        for _ in range(1000):
            page, next_cursor = await gateway.list_funds(funds_cursor)
            funds.extend(page)
            if not next_cursor:
                break
            if next_cursor in seen_fund_cursors:
                raise GatewayTerminalError(
                    "资金流水分页游标重复", code="invalid_upstream_pagination"
                )
            seen_fund_cursors.add(next_cursor)
            funds_cursor = next_cursor
        else:
            raise GatewayTerminalError(
                "资金流水分页超过安全上限", code="upstream_pagination_limit"
            )
        for _ in range(1000):
            page, next_cursor = await gateway.list_bills(
                product_id, bill_date, bill_cursor
            )
            bills.extend(page)
            if not next_cursor:
                break
            if next_cursor in seen_bill_cursors:
                raise GatewayTerminalError(
                    "券账单分页游标重复", code="invalid_upstream_pagination"
                )
            seen_bill_cursors.add(next_cursor)
            bill_cursor = next_cursor
        else:
            raise GatewayTerminalError(
                "券账单分页超过安全上限", code="upstream_pagination_limit"
            )
        for raw in funds:
            if not isinstance(raw, dict):
                continue
            external_id = str(
                raw.get("id", raw.get("external_id", raw.get("flow_id", "")))
            ).strip()
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
                identity = "|".join(
                    str(raw.get(key, ""))
                    for key in ("product_id", "order_id", "code", "time_index", "consume_time")
                )
                if identity.strip("|"):
                    external_id = "bill:" + hashlib.sha256(identity.encode()).hexdigest()
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
            bill.bill_type = "refund" if _as_int(raw.get("refund_amount")) else "settlement"
            bill.amount = _as_int(raw.get("mch_settle_amount", raw.get("amount")))
            bill.currency = str(raw.get("currency", "CNY"))
            bill.occurred_at = _as_datetime(
                raw.get("mch_settle_time", raw.get("consume_time", raw.get("occurred_at")))
            )
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
