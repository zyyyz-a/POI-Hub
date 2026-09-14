"""SaaS billing rules: plans, subscriptions, usage, invoices, and ledger entries."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    BillingAdjustment,
    BillingInvoice,
    BillingInvoiceItem,
    BillingPayment,
    BillingPlan,
    BillingSubscription,
    BillingUsageEvent,
    utcnow,
)


class BillingError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class BillingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_plans(self) -> list[BillingPlan]:
        rows = await self.session.execute(
            select(BillingPlan).order_by(BillingPlan.created_at.desc(), BillingPlan.id)
        )
        return list(rows.scalars().all())

    async def get_plan(self, plan_id: str) -> BillingPlan | None:
        return (
            await self.session.execute(select(BillingPlan).where(BillingPlan.id == plan_id))
        ).scalar_one_or_none()

    async def create_plan(self, values: dict[str, Any]) -> BillingPlan:
        row = BillingPlan(**values)
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise BillingError("plan_exists", "套餐编码已存在", 409) from error
        await self.session.refresh(row)
        return row

    async def update_plan(self, plan_id: str, version: int, changes: dict[str, Any]) -> BillingPlan:
        row = await self.session.scalar(
            select(BillingPlan).where(BillingPlan.id == plan_id)
        )
        if row is None:
            raise BillingError("plan_not_found", "套餐不存在", 404)
        if row.version != version:
            raise BillingError("version_conflict", "套餐已被他人修改，请刷新", 409)
        for key, value in changes.items():
            setattr(row, key, value)
        row.version += 1
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_subscriptions(self, tenant_id: str | None = None) -> list[BillingSubscription]:
        query = select(BillingSubscription)
        if tenant_id is not None:
            query = query.where(BillingSubscription.tenant_id == tenant_id)
        rows = await self.session.execute(
            query.order_by(BillingSubscription.created_at.desc(), BillingSubscription.id)
        )
        return list(rows.scalars().all())

    async def get_subscription(self, tenant_id: str) -> BillingSubscription | None:
        return (
            await self.session.execute(
                select(BillingSubscription).where(BillingSubscription.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()

    async def subscribe(
        self,
        tenant_id: str,
        plan_id: str,
        *,
        period_start: datetime | None,
        grace_days: int,
    ) -> BillingSubscription:
        plan = await self.session.scalar(select(BillingPlan).where(BillingPlan.id == plan_id))
        if plan is None:
            raise BillingError("plan_not_found", "套餐不存在", 404)
        existing = await self.get_subscription(tenant_id)
        if existing is not None:
            raise BillingError("subscription_exists", "该商户已有订阅", 409)
        start = _aware(period_start) if period_start else utcnow()
        row = BillingSubscription(
            tenant_id=tenant_id,
            plan_id=plan_id,
            status="active",
            current_period_start=start,
            current_period_end=start + timedelta(days=plan.period_days),
            grace_until=start + timedelta(days=plan.period_days + grace_days),
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise BillingError("subscription_exists", "该商户已有订阅", 409) from error
        await self.session.refresh(row)
        return row

    async def update_subscription(
        self, subscription_id: str, version: int, changes: dict[str, Any]
    ) -> BillingSubscription:
        row = await self.session.scalar(
            select(BillingSubscription).where(BillingSubscription.id == subscription_id)
        )
        if row is None:
            raise BillingError("subscription_not_found", "订阅不存在", 404)
        if row.version != version:
            raise BillingError("version_conflict", "订阅已被他人修改，请刷新", 409)
        for key, value in changes.items():
            setattr(row, key, value)
        row.version += 1
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def record_usage(self, values: dict[str, Any]) -> BillingUsageEvent:
        tenant_id = str(values["tenant_id"])
        idempotency_key = str(values["idempotency_key"])
        existing = await self.session.scalar(
            select(BillingUsageEvent).where(
                BillingUsageEvent.tenant_id == tenant_id,
                BillingUsageEvent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        subscription = await self.get_subscription(tenant_id)
        quantity = int(values["quantity"])
        unit_amount = int(values["unit_amount"])
        occurred_at = values.get("occurred_at") or utcnow()
        row = BillingUsageEvent(
            tenant_id=tenant_id,
            subscription_id=subscription.id if subscription else None,
            event_type=str(values["event_type"]),
            quantity=quantity,
            unit_amount=unit_amount,
            amount=quantity * unit_amount,
            idempotency_key=idempotency_key,
            occurred_at=_aware(occurred_at),
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            duplicate = await self.session.scalar(
                select(BillingUsageEvent).where(
                    BillingUsageEvent.tenant_id == tenant_id,
                    BillingUsageEvent.idempotency_key == idempotency_key,
                )
            )
            if duplicate is None:
                raise BillingError("usage_conflict", "计费事件写入冲突", 409) from None
            return duplicate
        await self.session.refresh(row)
        return row

    async def generate_invoice(
        self,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime,
        *,
        due_at: datetime | None,
        description: str,
        amount: int | None,
    ) -> BillingInvoice:
        subscription = await self.get_subscription(tenant_id)
        start = _aware(period_start)
        end = _aware(period_end)
        if end <= start:
            raise BillingError("invalid_period", "账期结束必须晚于开始")
        events = list(
            (
                await self.session.execute(
                    select(BillingUsageEvent)
                    .where(
                        BillingUsageEvent.tenant_id == tenant_id,
                        BillingUsageEvent.occurred_at >= start,
                        BillingUsageEvent.occurred_at < end,
                    )
                    .order_by(BillingUsageEvent.occurred_at, BillingUsageEvent.id)
                )
            )
            .scalars()
            .all()
        )
        items: list[BillingInvoiceItem] = []
        if amount is not None:
            items.append(
                BillingInvoiceItem(
                    description=description,
                    quantity=1,
                    unit_amount=amount,
                    amount=amount,
                    source_type="manual",
                )
            )
        else:
            grouped: dict[str, list[BillingUsageEvent]] = {}
            for event in events:
                grouped.setdefault(event.event_type, []).append(event)
            for event_type, group in grouped.items():
                quantity = sum(item.quantity for item in group)
                total = sum(item.amount for item in group)
                items.append(
                    BillingInvoiceItem(
                        description=f"{description} · {event_type}",
                        quantity=quantity,
                        unit_amount=group[0].unit_amount,
                        amount=total,
                        source_type="usage",
                        source_id=group[0].id,
                    )
                )
        total_amount = sum(item.amount for item in items)
        if total_amount <= 0:
            raise BillingError("invoice_empty", "账期内没有可计费金额", 409)
        invoice = BillingInvoice(
            tenant_id=tenant_id,
            subscription_id=subscription.id if subscription else None,
            invoice_no="INV" + utcnow().strftime("%Y%m%d%H%M%S") + secrets.token_hex(3).upper(),
            period_start=start,
            period_end=end,
            amount=total_amount,
            status="issued",
            due_at=_aware(due_at) if due_at else end + timedelta(days=7),
        )
        self.session.add(invoice)
        await self.session.flush()
        for item in items:
            item.invoice_id = invoice.id
            self.session.add(item)
        await self.session.commit()
        await self.session.refresh(invoice)
        return invoice

    async def list_invoices(self, tenant_id: str | None = None) -> list[BillingInvoice]:
        query = select(BillingInvoice)
        if tenant_id is not None:
            query = query.where(BillingInvoice.tenant_id == tenant_id)
        rows = await self.session.execute(
            query.order_by(BillingInvoice.created_at.desc(), BillingInvoice.id)
        )
        return list(rows.scalars().all())

    async def get_invoice(self, invoice_id: str) -> BillingInvoice:
        row = await self.session.scalar(
            select(BillingInvoice).where(BillingInvoice.id == invoice_id)
        )
        if row is None:
            raise BillingError("invoice_not_found", "账单不存在", 404)
        return row

    async def list_invoice_items(self, invoice_id: str) -> list[BillingInvoiceItem]:
        rows = await self.session.execute(
            select(BillingInvoiceItem)
            .where(BillingInvoiceItem.invoice_id == invoice_id)
            .order_by(BillingInvoiceItem.created_at, BillingInvoiceItem.id)
        )
        return list(rows.scalars().all())

    async def record_payment(
        self,
        invoice_id: str,
        *,
        amount: int,
        method: str,
        reference: str | None,
        received_at: datetime | None,
        actor_user_id: str | None,
    ) -> BillingPayment:
        invoice = await self.get_invoice(invoice_id)
        if invoice.status == "void":
            raise BillingError("invoice_void", "已作废账单不能收款", 409)
        remaining = invoice.amount - invoice.paid_amount
        if amount > remaining:
            raise BillingError("overpayment", "收款金额超过应收余额", 422)
        payment = BillingPayment(
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            amount=amount,
            method=method,
            reference=reference,
            received_at=_aware(received_at) if received_at else utcnow(),
            recorded_by_user_id=actor_user_id,
        )
        self.session.add(payment)
        invoice.paid_amount += amount
        invoice.status = "paid" if invoice.paid_amount >= invoice.amount else "partially_paid"
        invoice.version += 1
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def record_adjustment(
        self,
        invoice_id: str | None,
        *,
        kind: str,
        amount: int,
        reason: str,
        actor_user_id: str | None,
    ) -> BillingAdjustment:
        tenant_id: str
        if invoice_id is not None:
            invoice = await self.get_invoice(invoice_id)
            tenant_id = invoice.tenant_id
            new_amount = max(0, invoice.amount + amount)
            invoice.amount = new_amount
            invoice.status = (
                "paid"
                if invoice.paid_amount >= new_amount and new_amount > 0
                else invoice.status
            )
            invoice.version += 1
        else:
            raise BillingError("invoice_required", "必须关联账单", 422)
        row = BillingAdjustment(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            kind=kind,
            amount=amount,
            reason=reason,
            created_by_user_id=actor_user_id,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_adjustments(self, tenant_id: str | None = None) -> list[BillingAdjustment]:
        query = select(BillingAdjustment)
        if tenant_id is not None:
            query = query.where(BillingAdjustment.tenant_id == tenant_id)
        rows = await self.session.execute(
            query.order_by(BillingAdjustment.created_at.desc(), BillingAdjustment.id)
        )
        return list(rows.scalars().all())

    async def subscription_blockers(self, tenant_id: str) -> list[str]:
        subscription = await self.get_subscription(tenant_id)
        if subscription is None:
            return []
        now = utcnow()
        blockers: list[str] = []
        if subscription.status in {"suspended", "cancelled"}:
            blockers.append("商户订阅已停用")
        elif subscription.status == "past_due":
            blockers.append("商户订阅已逾期")
        elif (
            _aware(subscription.current_period_end) <= now
            and (subscription.grace_until is None or _aware(subscription.grace_until) <= now)
        ):
            blockers.append("商户订阅已过期且超出宽限期")
        return blockers

    async def outstanding_amount(self, tenant_id: str) -> int:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(BillingInvoice.amount - BillingInvoice.paid_amount), 0))
            .where(
                BillingInvoice.tenant_id == tenant_id,
                BillingInvoice.status.in_(["issued", "overdue", "partially_paid"]),
            )
        )
        return int(total or 0)

    async def run_maintenance(self) -> dict[str, int]:
        now = utcnow()
        overdue = list(
            (
                await self.session.execute(
                    select(BillingInvoice).where(
                        BillingInvoice.status.in_(["issued", "partially_paid"]),
                        BillingInvoice.due_at.is_not(None),
                        BillingInvoice.due_at < now,
                    )
                )
            )
            .scalars()
            .all()
        )
        for invoice in overdue:
            invoice.status = "overdue"
            invoice.version += 1
        subscriptions = list(
            (
                await self.session.execute(
                    select(BillingSubscription).where(
                        BillingSubscription.status.in_(["active", "past_due"])
                    )
                )
            )
            .scalars()
            .all()
        )
        for subscription in subscriptions:
            if subscription.grace_until is not None and _aware(subscription.grace_until) < now:
                subscription.status = "suspended"
                subscription.version += 1
            elif (
                _aware(subscription.current_period_end) < now
                and subscription.status == "active"
            ):
                subscription.status = "past_due"
                subscription.version += 1
        if overdue or subscriptions:
            await self.session.commit()
        return {"overdue_invoices": len(overdue)}


__all__ = ["BillingError", "BillingService"]
