"""Idempotent callback inbox handlers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.audit.service import AuditService
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability
from poi_admin.local_life.models import LocalProduct, ProductStatus

from .models import WebhookEvent, utcnow


def _event_product_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("product_id") or payload.get("ProductId") or payload.get("out_product_id")
    return str(value) if value is not None else None


async def process_webhook_event(session: AsyncSession, event: WebhookEvent) -> str:
    """Apply supported state hints; unknown events remain observable as processed."""
    if event.status == "processed":
        return event.status
    connection = (
        await session.execute(
            select(WeChatConnection).where(WeChatConnection.id == event.connection_id)
        )
    ).scalar_one_or_none()
    payload = event.payload if isinstance(event.payload, dict) else {}
    if connection is not None and connection.capability == Capability.LOCAL_LIFE.value:
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
    event.attempt_count += 1
    event.error_message = None
    await session.commit()
    return event.status


__all__ = ["process_webhook_event"]
