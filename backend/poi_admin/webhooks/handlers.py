"""Idempotent callback inbox handlers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.audit.service import AuditService
from poi_admin.connections.crypto import decrypt_secret_bundle
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, VoucherResult
from poi_admin.core.config import Settings
from poi_admin.local_life.models import LocalOrder, LocalProduct, ProductStatus
from poi_admin.local_life.vouchers import VoucherService

from .models import WebhookEvent, utcnow


def _event_product_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("product_id") or payload.get("ProductId") or payload.get("out_product_id")
    return str(value) if value is not None else None


async def process_webhook_event(
    session: AsyncSession, event: WebhookEvent, settings: Settings | None = None
) -> str:
    """Apply supported state hints; unknown events remain observable as processed."""
    if event.status == "processed":
        return event.status
    was_claimed = event.status == "processing"
    connection = (
        await session.execute(
            select(WeChatConnection).where(WeChatConnection.id == event.connection_id)
        )
    ).scalar_one_or_none()
    payload = event.payload if isinstance(event.payload, dict) else {}
    if event.encrypted_payload and settings is not None:
        payload = decrypt_secret_bundle(event.encrypted_payload, settings.encryption_key)
    if connection is not None and connection.capability == Capability.LOCAL_LIFE.value:
        if event.event_type.casefold() == "channels_ec_voucher_send_succ":
            voucher_items = payload.get("voucher_list", [])
            if isinstance(voucher_items, list):
                voucher_service = VoucherService(session, settings=settings)
                states = {
                    1: "available",
                    2: "consumed",
                    3: "refunded",
                    4: "expired",
                    5: "reserved",
                }
                for item in voucher_items:
                    if not isinstance(item, dict):
                        continue
                    code = item.get("code")
                    if not isinstance(code, str) or not code:
                        continue
                    order_id = str(item.get("order_id") or "").strip()
                    local_order: LocalOrder | None = None
                    if order_id:
                        local_order = (
                            await session.execute(
                                select(LocalOrder).where(
                                    LocalOrder.tenant_id == event.tenant_id,
                                    LocalOrder.connection_id == connection.id,
                                    LocalOrder.external_order_id == order_id,
                                )
                            )
                        ).scalar_one_or_none()
                        if local_order is None:
                            local_order = LocalOrder(
                                tenant_id=event.tenant_id,
                                connection_id=connection.id,
                                external_order_id=order_id,
                                status="paid",
                            )
                            session.add(local_order)
                            await session.flush()
                    try:
                        state = states.get(int(item.get("status", 1)), "available")
                    except (TypeError, ValueError):
                        state = "available"
                    await voucher_service.upsert_remote_voucher(
                        event.tenant_id,
                        connection.id,
                        VoucherResult(
                            code,
                            state,
                            str(item.get("product_id") or "") or None,
                            str(
                                item.get("out_store_id")
                                or item.get("consume_store_name")
                                or ""
                            )
                            or None,
                            item,
                        ),
                        order_id=local_order.id if local_order is not None else None,
                    )
        product_id = _event_product_id(payload)
        if product_id:
            product = (
                await session.execute(
                    select(LocalProduct).where(
                        LocalProduct.tenant_id == event.tenant_id,
                        LocalProduct.connection_id == connection.id,
                        (LocalProduct.external_product_id == product_id)
                        | (LocalProduct.merchant_product_id == product_id),
                    )
                )
            ).scalar_one_or_none()
            if product is not None:
                event_type = event.event_type.casefold()
                if "audit" in event_type:
                    product.remote_status = str(
                        payload.get("status", ProductStatus.UNDER_REVIEW.value)
                    )
                elif "listing" in event_type or event_type in {"product_listed", "listed"}:
                    product.remote_status = ProductStatus.LISTED.value
                elif "delist" in event_type or event_type in {"product_delisted", "delisted"}:
                    product.remote_status = ProductStatus.DELISTED.value
                product.last_synced_at = utcnow()
                product.version += 1
                await AuditService(session).record(
                    tenant_id=event.tenant_id,
                    actor_user_id=None,
                    action="webhook.product.updated",
                    resource_type="local_product",
                    resource_id=product.id,
                    after={"remote_status": product.remote_status, "event_type": event.event_type},
                )
    event.status = "processed"
    event.processed_at = utcnow()
    if not was_claimed:
        event.attempt_count += 1
    event.error_message = None
    event.worker_id = None
    event.lease_expires_at = None
    await session.commit()
    return event.status


__all__ = ["process_webhook_event"]
