"""WeChat Pay trade-bill parsing and per-order reconciliation."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    DirectOrder,
    DirectReconciliationBatch,
    DirectReconciliationItem,
)

PAID_STATUSES = {"paid", "partially_refunded", "refunded"}

_ORDER_NO_KEYS = ("商户订单号", "out_trade_no", "order_no")
_TRANSACTION_KEYS = ("微信订单号", "transaction_id")
_STATE_KEYS = ("交易状态", "trade_state")
_AMOUNT_KEYS = ("订单金额", "应结订单金额", "amount", "total")
_REFUND_KEYS = ("退款金额", "refund_amount")
_OUT_REFUND_KEYS = ("商户退款单号", "out_refund_no")


class DirectReconciliationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class StatementRow:
    order_no: str
    transaction_id: str | None
    trade_state: str
    amount: int
    refund_amount: int
    out_refund_no: str | None


def _to_cents(value: object) -> int:
    if value is None:
        return 0
    text = str(value).strip().strip("`").strip()
    if not text:
        return 0
    normalized = text.replace(",", "")
    try:
        return int(round(float(normalized) * 100))
    except ValueError:
        return 0


def _pick(record: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        for raw_key, raw_value in record.items():
            if raw_key and key in raw_key:
                value = (raw_value or "").strip().strip("`")
                if value:
                    return value
    return None


def parse_trade_bill_csv(text: str) -> list[StatementRow]:
    """Parse a WeChat Pay trade bill CSV into normalized statement rows."""

    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    rows = list(reader)
    if not rows:
        return []
    header = [cell.strip().strip("`") for cell in rows[0]]
    result: list[StatementRow] = []
    for raw in rows[1:]:
        if not raw or not any(cell.strip() for cell in raw):
            continue
        record = {
            header[index] if index < len(header) else f"col{index}": cell
            for index, cell in enumerate(raw)
        }
        order_no = _pick(record, _ORDER_NO_KEYS)
        if not order_no or order_no.startswith("总"):
            continue
        result.append(
            StatementRow(
                order_no=order_no,
                transaction_id=_pick(record, _TRANSACTION_KEYS),
                trade_state=(_pick(record, _STATE_KEYS) or "SUCCESS").upper(),
                amount=_to_cents(_pick(record, _AMOUNT_KEYS)),
                refund_amount=_to_cents(_pick(record, _REFUND_KEYS)),
                out_refund_no=_pick(record, _OUT_REFUND_KEYS),
            )
        )
    return result


def normalize_rows(rows: list[dict[str, Any]]) -> list[StatementRow]:
    """Normalize JSON rows; ``amount`` is interpreted as yuan."""

    result: list[StatementRow] = []
    for row in rows:
        order_no = str(row.get("order_no") or row.get("out_trade_no") or "").strip()
        if not order_no:
            continue
        amount = row.get("amount_cents")
        if amount is None:
            amount = _to_cents(row.get("amount"))
        refund = row.get("refund_amount_cents")
        if refund is None:
            refund = _to_cents(row.get("refund_amount"))
        result.append(
            StatementRow(
                order_no=order_no,
                transaction_id=(str(row["transaction_id"]) if row.get("transaction_id") else None),
                trade_state=str(row.get("trade_state") or "SUCCESS").upper(),
                amount=int(amount or 0),
                refund_amount=int(refund or 0),
                out_refund_no=(
                    str(row["out_refund_no"]) if row.get("out_refund_no") else None
                ),
            )
        )
    return result


class DirectReconciliationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_statement(
        self,
        tenant_id: str,
        bill_date: str,
        rows: list[StatementRow],
        actor_user_id: str | None,
        *,
        source: str = "import",
    ) -> DirectReconciliationBatch:
        try:
            datetime.fromisoformat(bill_date)
        except ValueError as error:
            raise DirectReconciliationError("invalid_bill_date", "账单日期格式无效") from error
        existing = await self.session.scalar(
            select(DirectReconciliationBatch).where(
                DirectReconciliationBatch.tenant_id == tenant_id,
                DirectReconciliationBatch.provider == "wechatpay",
                DirectReconciliationBatch.bill_date == bill_date,
            )
        )
        if existing is not None:
            raise DirectReconciliationError("reconciliation_exists", "该日期账单已导入", 409)

        statement = {row.order_no: row for row in rows}
        platform_orders = list(
            (
                await self.session.execute(
                    select(DirectOrder).where(
                        DirectOrder.tenant_id == tenant_id,
                        DirectOrder.order_no.in_(list(statement.keys()) or [""]),
                    )
                )
            )
            .scalars()
            .all()
        )
        platform_by_order = {order.order_no: order for order in platform_orders}

        batch = DirectReconciliationBatch(
            tenant_id=tenant_id,
            bill_date=bill_date,
            source=source,
            created_by_user_id=actor_user_id,
        )
        self.session.add(batch)
        await self.session.flush()

        items: list[DirectReconciliationItem] = []
        statement_total = 0
        platform_total = 0
        matched = 0
        for order_no, row in statement.items():
            statement_total += row.amount
            order = platform_by_order.get(order_no)
            if order is None:
                items.append(
                    DirectReconciliationItem(
                        batch_id=batch.id,
                        tenant_id=tenant_id,
                        order_no=order_no,
                        transaction_id=row.transaction_id,
                        statement_amount=row.amount,
                        status="missing_platform",
                        note="账单存在但平台无订单",
                    )
                )
                continue
            platform_total += order.total_amount
            if order.total_amount != row.amount:
                items.append(
                    DirectReconciliationItem(
                        batch_id=batch.id,
                        tenant_id=tenant_id,
                        order_no=order_no,
                        transaction_id=order.transaction_id,
                        statement_amount=row.amount,
                        platform_amount=order.total_amount,
                        status="amount_mismatch",
                        note="账单金额与平台金额不一致",
                    )
                )
            elif (
                row.trade_state not in {"SUCCESS", "REFUND", "退款"}
                and order.status in PAID_STATUSES
            ):
                items.append(
                    DirectReconciliationItem(
                        batch_id=batch.id,
                        tenant_id=tenant_id,
                        order_no=order_no,
                        transaction_id=order.transaction_id,
                        statement_amount=row.amount,
                        platform_amount=order.total_amount,
                        status="status_mismatch",
                        note=f"账单状态 {row.trade_state} 与平台状态 {order.status} 不一致",
                    )
                )
            else:
                matched += 1
                items.append(
                    DirectReconciliationItem(
                        batch_id=batch.id,
                        tenant_id=tenant_id,
                        order_no=order_no,
                        transaction_id=order.transaction_id,
                        statement_amount=row.amount,
                        platform_amount=order.total_amount,
                        status="matched",
                    )
                )

        items.extend(await self._missing_statement_items(tenant_id, batch.id, bill_date, statement))
        for item in items:
            self.session.add(item)

        batch.statement_total = statement_total
        batch.platform_total = platform_total
        batch.matched_count = matched
        batch.difference_count = sum(1 for item in items if item.status != "matched")
        batch.status = "completed"
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise DirectReconciliationError(
                "reconciliation_exists", "该日期账单已导入", 409
            ) from error
        await self.session.refresh(batch)
        return batch

    async def _missing_statement_items(
        self, tenant_id: str, batch_id: str, bill_date: str, statement: dict[str, StatementRow]
    ) -> list[DirectReconciliationItem]:
        start = datetime.fromisoformat(bill_date).replace(tzinfo=UTC)
        end = start + timedelta(days=1)
        orders = list(
            (
                await self.session.execute(
                    select(DirectOrder).where(
                        DirectOrder.tenant_id == tenant_id,
                        DirectOrder.paid_at.is_not(None),
                        DirectOrder.paid_at >= start,
                        DirectOrder.paid_at < end,
                    )
                )
            )
            .scalars()
            .all()
        )
        return [
            DirectReconciliationItem(
                batch_id=batch_id,
                tenant_id=tenant_id,
                order_no=order.order_no,
                transaction_id=order.transaction_id,
                statement_amount=None,
                platform_amount=order.total_amount,
                status="missing_statement",
                note="平台已支付但账单缺失",
            )
            for order in orders
            if order.order_no not in statement
        ]

    async def list_batches(self, tenant_id: str) -> list[DirectReconciliationBatch]:
        rows = await self.session.execute(
            select(DirectReconciliationBatch)
            .where(DirectReconciliationBatch.tenant_id == tenant_id)
            .order_by(DirectReconciliationBatch.created_at.desc())
        )
        return list(rows.scalars().all())

    async def get_batch(self, tenant_id: str, batch_id: str) -> DirectReconciliationBatch:
        row = await self.session.scalar(
            select(DirectReconciliationBatch).where(
                DirectReconciliationBatch.tenant_id == tenant_id,
                DirectReconciliationBatch.id == batch_id,
            )
        )
        if row is None:
            raise DirectReconciliationError("reconciliation_not_found", "对账批次不存在", 404)
        return row

    async def list_items(
        self, tenant_id: str, batch_id: str
    ) -> list[DirectReconciliationItem]:
        await self.get_batch(tenant_id, batch_id)
        rows = await self.session.execute(
            select(DirectReconciliationItem)
            .where(
                DirectReconciliationItem.tenant_id == tenant_id,
                DirectReconciliationItem.batch_id == batch_id,
            )
            .order_by(DirectReconciliationItem.status, DirectReconciliationItem.order_no)
        )
        return list(rows.scalars().all())

    async def resolve_item(
        self, tenant_id: str, item_id: str, note: str
    ) -> DirectReconciliationItem:
        row = await self.session.scalar(
            select(DirectReconciliationItem).where(
                DirectReconciliationItem.tenant_id == tenant_id,
                DirectReconciliationItem.id == item_id,
            )
        )
        if row is None:
            raise DirectReconciliationError("reconciliation_item_not_found", "差异项不存在", 404)
        if row.status == "matched":
            raise DirectReconciliationError("reconciliation_item_matched", "一致项无需处理", 409)
        row.resolved = True
        row.resolved_note = note
        await self.session.commit()
        await self.session.refresh(row)
        return row


__all__ = [
    "DirectReconciliationError",
    "DirectReconciliationService",
    "StatementRow",
    "normalize_rows",
    "parse_trade_bill_csv",
]
