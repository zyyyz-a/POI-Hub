"""Unauthenticated public WeChat callback endpoints."""

from __future__ import annotations

import json
from typing import Annotated, NoReturn, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.core.config import Settings
from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, require_csrf, require_permission
from poi_admin.core.permissions import Permission

from .models import WebhookEvent
from .service import WebhookService, WebhookServiceError

webhook_router = APIRouter(prefix="/callbacks/wechat", tags=["webhooks"])
webhook_events_router = APIRouter(prefix="/webhook-events", tags=["webhooks"])
MAX_BODY_BYTES = 512 * 1024


@webhook_events_router.get("")
async def list_webhook_events(
    context: AuthContext = Depends(require_permission(Permission.VIEW_OPERATIONS)),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    if context.tenant is None:
        _raise(WebhookServiceError("tenant_required", "请先选择租户", 400))
    tenant_id = context.tenant.id
    rows = await session.execute(
        select(WebhookEvent)
        .where(WebhookEvent.tenant_id == tenant_id)
        .order_by(WebhookEvent.received_at.desc())
        .limit(100)
    )
    return [
        {
            "id": row.id,
            "event_type": row.event_type,
            "status": row.status,
            "attempt_count": row.attempt_count,
            "received_at": row.received_at,
            "error_message": row.error_message,
        }
        for row in rows.scalars().all()
    ]


@webhook_events_router.post("/{event_id}/retry")
async def retry_webhook_event(
    event_id: str,
    request: Request,
    context: AuthContext = Depends(require_permission(Permission.MANAGE_OPERATIONS)),
    csrf_context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    del csrf_context
    if context.tenant is None:
        _raise(WebhookServiceError("tenant_required", "请先选择租户", 400))
    try:
        event = await WebhookService(
            session, cast(Settings, request.app.state.settings)
        ).retry(
            context.tenant.id, event_id
        )
    except WebhookServiceError as error:
        _raise(error)
    return {
        "id": event.id,
        "event_type": event.event_type,
        "status": event.status,
        "attempt_count": event.attempt_count,
        "error_message": event.error_message,
    }


def _raise(error: WebhookServiceError) -> NoReturn:
    from poi_admin.core.dependencies import auth_error

    raise auth_error(error.code, error.message, error.status_code)


@webhook_router.get("/{connection_id}")
async def verify_callback(
    connection_id: str,
    request: Request,
    timestamp: Annotated[str, Query()],
    nonce: Annotated[str, Query()],
    signature: Annotated[str, Query(alias="signature")],
    echostr: Annotated[str, Query()],
    ) -> Response:
    async with request.app.state.database.session_factory() as session:
        try:
            connection = await WebhookService(session, request.app.state.settings).connection(
                connection_id
            )
            WebhookService(session, request.app.state.settings).verify(
                connection, token="", timestamp=timestamp, nonce=nonce, signature=signature
            )
        except WebhookServiceError as error:
            _raise(error)
    return Response(echostr, media_type="text/plain")


@webhook_router.post("/{connection_id}")
async def receive_callback(
    connection_id: str,
    request: Request,
    timestamp: Annotated[str, Query()],
    nonce: Annotated[str, Query()],
    signature: Annotated[str | None, Query()] = None,
    msg_signature: Annotated[str | None, Query(alias="msg_signature")] = None,
) -> Response:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return Response("body too large", status_code=413)
    async with request.app.state.database.session_factory() as session:
        service = WebhookService(session, request.app.state.settings)
        try:
            connection = await service.connection(connection_id)
            value = json.loads(body.decode("utf-8"))
            if not isinstance(value, dict):
                raise WebhookServiceError("invalid_callback_payload", "回调内容格式无效", 400)
            encrypted = value.get("Encrypt") or value.get("encrypt")
            if encrypted:
                if not msg_signature:
                    raise WebhookServiceError("invalid_callback_signature", "缺少回调签名", 403)
                service.verify(
                    connection,
                    token="",
                    timestamp=timestamp,
                    nonce=nonce,
                    signature=msg_signature,
                    encrypt=str(encrypted),
                )
                try:
                    value = service.decrypt_payload(connection, str(encrypted))
                except ValueError as error:
                    raise WebhookServiceError(
                        "invalid_callback_payload", "invalid encrypted callback payload", 400
                    ) from error
            else:
                if not signature:
                    raise WebhookServiceError(
                        "invalid_callback_signature", "missing callback signature", 403
                    )
                service.verify(
                    connection,
                    token="",
                    timestamp=timestamp,
                    nonce=nonce,
                    signature=signature,
                )
            await service.ingest(connection_id, value)
        except WebhookServiceError as error:
            _raise(error)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _raise(WebhookServiceError("invalid_callback_payload", "invalid callback JSON", 400))
    return Response("success", media_type="text/plain")


__all__ = ["webhook_events_router", "webhook_router"]
