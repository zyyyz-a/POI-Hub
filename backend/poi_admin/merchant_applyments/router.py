"""Administrator-only onboarding endpoints with bounded private request bodies."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.audit.service import AuditService
from poi_admin.core.config import Settings
from poi_admin.core.database import get_session
from poi_admin.core.dependencies import (
    AuthContext,
    auth_error,
    require_csrf,
    require_tenant_permission,
)
from poi_admin.core.permissions import Permission

from .limits import MAX_IMAGE_BYTES
from .models import MerchantApplyment
from .schemas import (
    ApplymentAction,
    ApplymentCapabilities,
    ApplymentResponse,
    CreateApplyment,
    SaveApplyment,
    SubmitApplyment,
)
from .service import ApplymentError, ApplymentService


class PrivateApplymentRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                if request.method in {"POST", "PUT", "PATCH"}:
                    limit = MAX_IMAGE_BYTES if "/attachments/" in request.url.path else 65536
                    content = bytearray()
                    async for chunk in request.stream():
                        content.extend(chunk)
                        if len(content) > limit:
                            raise ApplymentError("request_too_large", "资料超过允许大小", 413)
                    request._body = bytes(content)
                response = await original(request)
            except RequestValidationError:
                # Default validation responses include raw submitted identity/bank values.
                response = JSONResponse(
                    status_code=422,
                    content={
                        "detail": {
                            "code": "invalid_applyment_request",
                            "message": "资料格式或版本不正确，请检查填写内容后重试",
                        }
                    },
                )
            except ApplymentError as error:
                response = JSONResponse(
                    status_code=error.status,
                    content={
                        "detail": {
                            "code": error.code,
                            "message": error.message,
                        }
                    },
                )
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        return handler


applyment_router = APIRouter(
    prefix="/merchant-applyments",
    tags=["merchant-applyments"],
    route_class=PrivateApplymentRoute,
    dependencies=[Depends(require_tenant_permission(Permission.MANAGE_CONNECTIONS))],
)
Context = Annotated[AuthContext, Depends(require_tenant_permission(Permission.MANAGE_CONNECTIONS))]
Session = Annotated[AsyncSession, Depends(get_session)]
Csrf = Annotated[AuthContext, Depends(require_csrf)]


def service(request: Request, session: AsyncSession) -> ApplymentService:
    return ApplymentService(
        session, cast(Settings, request.app.state.settings), request.app.state.http_client
    )


def tenant_id(context: AuthContext) -> str:
    if context.tenant is None:
        raise auth_error("tenant_required", "请先选择商户", 400)
    return context.tenant.id


async def record(
    session: AsyncSession, context: AuthContext, row: MerchantApplyment, action: str
) -> None:
    # Never put fields, images, provider responses or sign links in audit logs.
    await AuditService(session).record(
        tenant_id=tenant_id(context),
        actor_user_id=context.user.id,
        action=f"merchant_applyment.{action}",
        resource_type="merchant_applyment",
        resource_id=row.id,
        after={"state": row.state, "version": row.version},
    )


@applyment_router.get("/capabilities", response_model=ApplymentCapabilities)
async def capabilities(request: Request) -> ApplymentCapabilities:
    return ApplymentCapabilities(
        real_submission_enabled=request.app.state.settings.wechat_applyment_submit_enabled,
    )


@applyment_router.get("", response_model=list[ApplymentResponse])
async def list_applyments(
    request: Request, context: Context, session: Session
) -> list[ApplymentResponse]:
    rows = (
        await session.scalars(
            select(MerchantApplyment)
            .where(
                MerchantApplyment.tenant_id == tenant_id(context),
            )
            .order_by(MerchantApplyment.updated_at.desc())
        )
    ).all()
    current = service(request, session)
    return [await current.present(row, detail=False) for row in rows]


@applyment_router.post("", response_model=ApplymentResponse, status_code=201)
async def create_applyment(
    payload: CreateApplyment,
    request: Request,
    context: Context,
    session: Session,
    csrf: Csrf,
) -> ApplymentResponse:
    del csrf
    current = service(request, session)
    row = await current.create(tenant_id(context), payload.store_id, payload.connection_id)
    await record(session, context, row, "create")
    return await current.present(row)


@applyment_router.get("/{application_id}", response_model=ApplymentResponse)
async def get_applyment(
    application_id: str,
    request: Request,
    context: Context,
    session: Session,
) -> ApplymentResponse:
    current = service(request, session)
    row = await current.get(tenant_id(context), application_id)
    await record(session, context, row, "view_private_draft")
    return await current.present(row)


@applyment_router.put("/{application_id}", response_model=ApplymentResponse)
async def save_applyment(
    application_id: str,
    payload: SaveApplyment,
    request: Request,
    context: Context,
    session: Session,
    csrf: Csrf,
) -> ApplymentResponse:
    del csrf
    current = service(request, session)
    row = await current.get(tenant_id(context), application_id)
    row = await current.save(row, payload.version, payload.fields)
    await record(session, context, row, "save")
    return await current.present(row)


@applyment_router.post("/{application_id}/attachments/{kind}", response_model=ApplymentResponse)
async def upload_attachment(
    application_id: str,
    kind: str,
    version: int,
    request: Request,
    context: Context,
    session: Session,
    csrf: Csrf,
) -> ApplymentResponse:
    del csrf
    current = service(request, session)
    row = await current.get(tenant_id(context), application_id)
    row = await current.attach(row, version, kind, await request.body())
    await record(session, context, row, "save_attachment")
    return await current.present(row)


@applyment_router.delete("/{application_id}/attachments/{kind}", response_model=ApplymentResponse)
async def delete_attachment(
    application_id: str,
    kind: str,
    version: int,
    request: Request,
    context: Context,
    session: Session,
    csrf: Csrf,
) -> ApplymentResponse:
    del csrf
    current = service(request, session)
    row = await current.get(tenant_id(context), application_id)
    row = await current.remove_attachment(row, version, kind)
    await record(session, context, row, "remove_attachment")
    return await current.present(row)


@applyment_router.post("/{application_id}/submit", response_model=ApplymentResponse)
async def submit_applyment(
    application_id: str,
    payload: SubmitApplyment,
    request: Request,
    context: Context,
    session: Session,
    csrf: Csrf,
) -> ApplymentResponse:
    del csrf
    current = service(request, session)
    row = await current.get(tenant_id(context), application_id)
    row = await current.submit(row, payload.version, context.user.id)
    await record(session, context, row, "submit")
    return await current.present(row)


@applyment_router.post("/{application_id}/sync", response_model=ApplymentResponse)
async def sync_applyment(
    application_id: str,
    payload: ApplymentAction,
    request: Request,
    context: Context,
    session: Session,
    csrf: Csrf,
) -> ApplymentResponse:
    del csrf
    current = service(request, session)
    row = await current.get(tenant_id(context), application_id)
    row = await current.sync(row, payload.version)
    await record(session, context, row, "sync")
    return await current.present(row)


@applyment_router.post("/{application_id}/link-payment")
async def link_payment(
    application_id: str,
    payload: ApplymentAction,
    request: Request,
    context: Context,
    session: Session,
    csrf: Csrf,
) -> dict[str, str]:
    del csrf
    current = service(request, session)
    row = await current.get(tenant_id(context), application_id)
    profile_id = await current.link_payment(row, payload.version)
    await record(session, context, row, "link_payment_draft")
    return {"payment_profile_id": profile_id, "message": "已关联支付档案，未自动启用收款"}
