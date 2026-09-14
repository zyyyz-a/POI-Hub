"""Admin and consumer HTTP endpoints for direct mini-program commerce."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.audit.service import AuditService
from poi_admin.core.config import Settings
from poi_admin.core.database import get_session
from poi_admin.core.dependencies import AuthContext, auth_error, require_csrf, require_permission
from poi_admin.core.permissions import Permission

from .platform_service import PlatformCommerceService
from .schemas import (
    AppointmentCreate,
    AppointmentResponse,
    ConsumerLoginRequest,
    ConsumerSessionResponse,
    DirectOrderCreate,
    DirectOrderResponse,
    DirectProductCreate,
    DirectProductResponse,
    DirectProductUpdate,
    PaymentProfileCreate,
    PaymentProfileResponse,
    PaymentProfileUpdate,
    PaymentRequest,
    PaymentResponse,
    StoreEntryResponse,
    VoucherConsumeRequest,
    VoucherResponse,
    VoucherRevokeRequest,
)
from .service import DirectCommerceError, DirectCommerceService

direct_commerce_router = APIRouter(prefix="/direct-commerce", tags=["direct-commerce"])
consumer_router = APIRouter(prefix="/public/mini-programs", tags=["mini-program-consumer"])
platform_router = APIRouter(prefix="/public/platform", tags=["platform-mini-program"])
payment_notify_router = APIRouter(prefix="/public/wechatpay", tags=["wechat-pay-notify"])


def _tenant_id(context: AuthContext) -> str:
    if context.tenant is None:
        raise auth_error("tenant_required", "请先选择租户", 400)
    return context.tenant.id


def _service(request: Request, session: AsyncSession) -> DirectCommerceService:
    return DirectCommerceService(
        session,
        cast(Settings, request.app.state.settings),
        http_client=getattr(request.app.state, "http_client", None),
    )


def _platform_service(request: Request, session: AsyncSession) -> PlatformCommerceService:
    return PlatformCommerceService(
        session,
        cast(Settings, request.app.state.settings),
        http_client=getattr(request.app.state, "http_client", None),
    )


def _raise(error: DirectCommerceError) -> None:
    raise auth_error(error.code, error.message, error.status_code)


def _bearer(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer ") or not value[7:].strip():
        raise auth_error("consumer_authentication_required", "请先登录小程序", 401)
    return value[7:].strip()


async def _audit(
    session: AsyncSession,
    request: Request,
    context: AuthContext,
    action: str,
    resource_type: str,
    resource_id: str,
    after: dict[str, Any],
) -> None:
    await AuditService(session).record(
        tenant_id=_tenant_id(context),
        actor_user_id=context.user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        after=after,
        correlation_id=getattr(request.state, "correlation_id", None),
    )


@direct_commerce_router.get("/products", response_model=list[DirectProductResponse])
async def list_products(
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_PRODUCTS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DirectProductResponse]:
    rows = await _service(request, session).list_products(_tenant_id(context))
    return [DirectProductResponse.model_validate(item) for item in rows]


@direct_commerce_router.post(
    "/products", response_model=DirectProductResponse, status_code=status.HTTP_201_CREATED
)
async def create_product(
    payload: DirectProductCreate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_PRODUCTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DirectProductResponse:
    del csrf_context
    try:
        row = await _service(request, session).create_product(
            _tenant_id(context), payload.model_dump()
        )
    except DirectCommerceError as error:
        _raise(error)
    response = DirectProductResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "direct_product.created",
        "direct_product",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@direct_commerce_router.patch("/products/{product_id}", response_model=DirectProductResponse)
async def update_product(
    product_id: str,
    payload: DirectProductUpdate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_PRODUCTS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DirectProductResponse:
    del csrf_context
    try:
        row = await _service(request, session).update_product(
            _tenant_id(context),
            product_id,
            payload.version,
            payload.model_dump(exclude={"version"}, exclude_unset=True),
        )
    except DirectCommerceError as error:
        _raise(error)
    response = DirectProductResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "direct_product.updated",
        "direct_product",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@direct_commerce_router.get("/orders", response_model=list[DirectOrderResponse])
async def list_orders(
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ORDERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DirectOrderResponse]:
    rows = await _service(request, session).list_orders(_tenant_id(context))
    return [DirectOrderResponse.model_validate(item) for item in rows]


@direct_commerce_router.get("/appointments", response_model=list[AppointmentResponse])
async def list_appointments(
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ORDERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AppointmentResponse]:
    rows = await _service(request, session).list_appointments(_tenant_id(context))
    return [AppointmentResponse.model_validate(item) for item in rows]


@direct_commerce_router.get("/vouchers", response_model=list[VoucherResponse])
async def list_vouchers(
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ORDERS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VoucherResponse]:
    rows = await _service(request, session).list_vouchers(_tenant_id(context))
    return [VoucherResponse.model_validate(item) for item in rows]


@direct_commerce_router.post("/vouchers/consume", response_model=VoucherResponse)
async def consume_voucher(
    payload: VoucherConsumeRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.CONSUME_VOUCHERS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VoucherResponse:
    del csrf_context
    try:
        row = await _service(request, session).consume_voucher(
            _tenant_id(context), payload.code, payload.store_id, context.user.id
        )
    except DirectCommerceError as error:
        _raise(error)
    response = VoucherResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "direct_voucher.consumed",
        "direct_voucher",
        row.id,
        {"state": row.state, "store_id": row.consume_store_id},
    )
    return response


@direct_commerce_router.post("/vouchers/{voucher_id}/revoke", response_model=VoucherResponse)
async def revoke_voucher(
    voucher_id: str,
    payload: VoucherRevokeRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.CONSUME_VOUCHERS))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VoucherResponse:
    del csrf_context
    try:
        row = await _service(request, session).revoke_voucher(
            _tenant_id(context), voucher_id, payload.version
        )
    except DirectCommerceError as error:
        _raise(error)
    response = VoucherResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "direct_voucher.consumption_revoked",
        "direct_voucher",
        row.id,
        {"state": row.state, "reason": payload.reason},
    )
    return response


@direct_commerce_router.get(
    "/payment-profiles", response_model=list[PaymentProfileResponse]
)
async def list_payment_profiles(
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.VIEW_ONBOARDING))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PaymentProfileResponse]:
    rows = await _service(request, session).list_payment_profiles(_tenant_id(context))
    return [PaymentProfileResponse.model_validate(item) for item in rows]


@direct_commerce_router.post(
    "/payment-profiles",
    response_model=PaymentProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_profile(
    payload: PaymentProfileCreate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentProfileResponse:
    del csrf_context
    try:
        row = await _service(request, session).create_payment_profile(
            _tenant_id(context), payload.model_dump()
        )
    except DirectCommerceError as error:
        _raise(error)
    response = PaymentProfileResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "payment_profile.created",
        "payment_profile",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@direct_commerce_router.patch(
    "/payment-profiles/{profile_id}", response_model=PaymentProfileResponse
)
async def update_payment_profile(
    profile_id: str,
    payload: PaymentProfileUpdate,
    request: Request,
    context: Annotated[AuthContext, Depends(require_permission(Permission.MANAGE_ONBOARDING))],
    csrf_context: Annotated[AuthContext, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentProfileResponse:
    del csrf_context
    try:
        row = await _service(request, session).update_payment_profile(
            _tenant_id(context),
            profile_id,
            payload.version,
            payload.model_dump(exclude={"version"}, exclude_unset=True),
        )
    except DirectCommerceError as error:
        _raise(error)
    response = PaymentProfileResponse.model_validate(row)
    await _audit(
        session,
        request,
        context,
        "payment_profile.updated",
        "payment_profile",
        row.id,
        response.model_dump(mode="json"),
    )
    return response


@consumer_router.post("/{mini_program_id}/login", response_model=ConsumerSessionResponse)
async def consumer_login(
    mini_program_id: str,
    payload: ConsumerLoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConsumerSessionResponse:
    try:
        token, expires_at = await _service(request, session).consumer_login(
            mini_program_id, payload.code
        )
    except DirectCommerceError as error:
        _raise(error)
    return ConsumerSessionResponse(access_token=token, expires_at=expires_at)


@consumer_router.get("/{mini_program_id}/products", response_model=list[DirectProductResponse])
async def public_products(
    mini_program_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DirectProductResponse]:
    try:
        rows = await _service(request, session).public_products(mini_program_id)
    except DirectCommerceError as error:
        _raise(error)
    return [DirectProductResponse.model_validate(item) for item in rows]


@consumer_router.post(
    "/{mini_program_id}/orders",
    response_model=DirectOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    mini_program_id: str,
    payload: DirectOrderCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DirectOrderResponse:
    service = _service(request, session)
    try:
        consumer = await service.consumer(_bearer(request), mini_program_id)
        row = await service.create_order(
            mini_program_id,
            consumer,
            payload.product_id,
            payload.quantity,
            payload.idempotency_key,
        )
    except DirectCommerceError as error:
        _raise(error)
    return DirectOrderResponse.model_validate(row)


@consumer_router.get("/{mini_program_id}/orders/{order_id}", response_model=DirectOrderResponse)
async def get_order(
    mini_program_id: str,
    order_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DirectOrderResponse:
    service = _service(request, session)
    try:
        consumer = await service.consumer(_bearer(request), mini_program_id)
        row = await service.consumer_order(mini_program_id, consumer.id, order_id)
    except DirectCommerceError as error:
        _raise(error)
    return DirectOrderResponse.model_validate(row)


@consumer_router.post("/{mini_program_id}/orders/{order_id}/pay", response_model=PaymentResponse)
async def pay_order(
    mini_program_id: str,
    order_id: str,
    payload: PaymentRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentResponse:
    service = _service(request, session)
    try:
        consumer = await service.consumer(_bearer(request), mini_program_id)
        order, parameters, mock_code = await service.pay_order(
            mini_program_id, consumer, order_id, payload.description
        )
    except DirectCommerceError as error:
        _raise(error)
    return PaymentResponse(
        order=DirectOrderResponse.model_validate(order),
        payment_parameters=parameters,
        mock_voucher_code=mock_code,
    )


@consumer_router.get("/{mini_program_id}/orders/{order_id}/voucher")
async def get_consumer_voucher(
    mini_program_id: str,
    order_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    service = _service(request, session)
    try:
        consumer = await service.consumer(_bearer(request), mini_program_id)
        voucher, code = await service.consumer_voucher(mini_program_id, consumer.id, order_id)
    except DirectCommerceError as error:
        _raise(error)
    return {"voucher": VoucherResponse.model_validate(voucher), "code": code}


@consumer_router.post(
    "/{mini_program_id}/orders/{order_id}/appointment",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_appointment(
    mini_program_id: str,
    order_id: str,
    payload: AppointmentCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AppointmentResponse:
    service = _service(request, session)
    try:
        consumer = await service.consumer(_bearer(request), mini_program_id)
        row = await service.create_appointment(
            mini_program_id, consumer, order_id, payload.model_dump()
        )
    except DirectCommerceError as error:
        _raise(error)
    return AppointmentResponse.model_validate(row)


@platform_router.get("/stores/{store_code}", response_model=StoreEntryResponse)
async def resolve_store_entry(
    store_code: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoreEntryResponse:
    service = _platform_service(request, session)
    try:
        entry = await service.resolve(store_code)
    except DirectCommerceError as error:
        _raise(error)
    blockers = service.blockers(entry)
    return StoreEntryResponse(
        store_code=entry.binding.store_code,
        store_name=entry.store.name,
        address=entry.store.address,
        city=entry.store.city,
        district=entry.store.district,
        contact_phone_masked=entry.store.contact_phone_masked,
        latitude=entry.store.latitude,
        longitude=entry.store.longitude,
        tradable=not blockers,
        blockers=blockers,
    )


@platform_router.post("/stores/{store_code}/login", response_model=ConsumerSessionResponse)
async def platform_consumer_login(
    store_code: str,
    payload: ConsumerLoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConsumerSessionResponse:
    try:
        token, expires_at = await _platform_service(request, session).login(
            store_code, payload.code
        )
    except DirectCommerceError as error:
        _raise(error)
    return ConsumerSessionResponse(access_token=token, expires_at=expires_at)


@platform_router.get("/stores/{store_code}/products", response_model=list[DirectProductResponse])
async def platform_products(
    store_code: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DirectProductResponse]:
    try:
        rows = await _platform_service(request, session).products(store_code)
    except DirectCommerceError as error:
        _raise(error)
    return [DirectProductResponse.model_validate(item) for item in rows]


@platform_router.post(
    "/stores/{store_code}/orders",
    response_model=DirectOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def platform_create_order(
    store_code: str,
    payload: DirectOrderCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DirectOrderResponse:
    service = _platform_service(request, session)
    try:
        _, consumer = await service.consumer(_bearer(request), store_code)
        row = await service.create_order(
            store_code,
            consumer,
            payload.product_id,
            payload.quantity,
            payload.idempotency_key,
        )
    except DirectCommerceError as error:
        _raise(error)
    return DirectOrderResponse.model_validate(row)


@platform_router.get(
    "/stores/{store_code}/orders/{order_id}", response_model=DirectOrderResponse
)
async def platform_get_order(
    store_code: str,
    order_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DirectOrderResponse:
    service = _platform_service(request, session)
    try:
        _, consumer = await service.consumer(_bearer(request), store_code)
        row = await service.order(store_code, consumer.id, order_id)
    except DirectCommerceError as error:
        _raise(error)
    return DirectOrderResponse.model_validate(row)


@platform_router.post(
    "/stores/{store_code}/orders/{order_id}/pay", response_model=PaymentResponse
)
async def platform_pay_order(
    store_code: str,
    order_id: str,
    payload: PaymentRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentResponse:
    service = _platform_service(request, session)
    try:
        _, consumer = await service.consumer(_bearer(request), store_code)
        order, parameters, mock_code = await service.pay_order(
            store_code, consumer, order_id, payload.description
        )
    except DirectCommerceError as error:
        _raise(error)
    return PaymentResponse(
        order=DirectOrderResponse.model_validate(order),
        payment_parameters=parameters,
        mock_voucher_code=mock_code,
    )


@platform_router.get("/stores/{store_code}/orders/{order_id}/voucher")
async def platform_consumer_voucher(
    store_code: str,
    order_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    service = _platform_service(request, session)
    try:
        _, consumer = await service.consumer(_bearer(request), store_code, tradable=False)
        voucher, code = await service.consumer_voucher(store_code, consumer.id, order_id)
    except DirectCommerceError as error:
        _raise(error)
    return {"voucher": VoucherResponse.model_validate(voucher), "code": code}


@platform_router.post(
    "/stores/{store_code}/orders/{order_id}/appointment",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def platform_create_appointment(
    store_code: str,
    order_id: str,
    payload: AppointmentCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AppointmentResponse:
    service = _platform_service(request, session)
    try:
        _, consumer = await service.consumer(_bearer(request), store_code)
        row = await service.create_appointment(
            store_code, consumer, order_id, payload.model_dump()
        )
    except DirectCommerceError as error:
        _raise(error)
    return AppointmentResponse.model_validate(row)


@payment_notify_router.post("/notify/{mini_program_id}")
async def payment_notification(
    mini_program_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    body = await request.body()
    try:
        await _service(request, session).handle_payment_notification(
            mini_program_id, dict(request.headers), body
        )
    except DirectCommerceError as error:
        return JSONResponse(
            status_code=error.status_code, content={"code": "FAIL", "message": error.message}
        )
    return JSONResponse(content={"code": "SUCCESS", "message": "成功"})


__all__ = [
    "consumer_router",
    "direct_commerce_router",
    "payment_notify_router",
    "platform_router",
]
