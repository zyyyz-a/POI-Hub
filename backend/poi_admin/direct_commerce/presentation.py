"""Batch consumer order presentation, derived from authoritative business records."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    DirectAppointment,
    DirectOrder,
    DirectProduct,
    DirectRefund,
    DirectVoucher,
    utcnow,
)
from .schemas import DirectOrderResponse
from .service import _aware


async def present_orders(
    session: AsyncSession, orders: list[DirectOrder], *, tradable: bool
) -> list[DirectOrderResponse]:
    if not orders:
        return []
    ids = [order.id for order in orders]
    vouchers = {
        row.order_id: row
        for row in (await session.scalars(select(DirectVoucher).where(
            DirectVoucher.order_id.in_(ids)
        ))).all()
    }
    refunds: dict[str, DirectRefund] = {}
    for row in (await session.scalars(select(DirectRefund).where(
        DirectRefund.order_id.in_(ids)
    ).order_by(DirectRefund.created_at.desc(), DirectRefund.id))).all():
        # An in-flight refund takes priority over a newer failed attempt.
        if row.order_id not in refunds or row.status in {"requested", "pending", "processing"}:
            refunds[row.order_id] = row
    booked = set((await session.scalars(select(DirectAppointment.order_id).where(
        DirectAppointment.order_id.in_(ids), DirectAppointment.status == "confirmed"
    ))).all())
    products = {
        row.id: row
        for row in (await session.scalars(select(DirectProduct).where(
            DirectProduct.id.in_([order.product_id for order in orders])
        ))).all()
    }
    now = utcnow()
    result = []
    for order in orders:
        voucher = vouchers.get(order.id)
        refund = refunds.get(order.id)
        refund_status = refund.status if refund else None
        refund_pending = refund_status in {"requested", "pending", "processing"}
        paid = order.status in {"paid", "partially_refunded"}
        usable = bool(paid and voucher and voucher.state == "available"
                      and _aware(voucher.valid_until) > now and not refund_pending)
        display = order.status
        if paid and voucher:
            if voucher.state == "consumed":
                display = "consumed"
            elif _aware(voucher.valid_until) <= now:
                display = "voucher_expired"
        if refund_pending:
            display = "refund_requested" if refund_status == "requested" else "refund_processing"
        elif refund_status == "failed" and paid:
            display = "refund_failed"
        product = products.get(order.product_id)
        view = DirectOrderResponse.model_validate(order)
        result.append(view.model_copy(update={
            "store_code": order.store_code_snapshot,
            "display_status": display,
            "voucher_state": voucher.state if voucher else None,
            "refund_status": refund_status,
            "can_pay": bool(tradable and order.status == "payment_pending"
                            and _aware(order.expires_at) > now),
            "can_book": bool(tradable and usable and product and product.appointment_required
                             and order.id not in booked),
            "can_show_voucher": usable,
            "can_refund": bool(usable and order.paid_amount > order.refunded_amount),
        }))
    return result
