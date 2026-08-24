"""Voucher lookup, masking, consumption and revoke operations."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.crypto import decrypt_secret_bundle, encrypt_secret_bundle
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import (
    Capability,
    GatewayTerminalError,
    GatewayTransientError,
    LocalLifeGateway,
    VoucherResult,
)
from poi_admin.connections.service import ConnectionService
from poi_admin.core.config import Settings
from poi_admin.operations.models import IntegrationOperation
from poi_admin.operations.service import OperationService
from poi_admin.operations.worker import Handler
from poi_admin.stores.models import Store, StorePoiMapping

from .models import LocalVoucher, utcnow

CONSUME_VOUCHER_COMMAND = "local_life.voucher.consume"
REVOKE_VOUCHER_COMMAND = "local_life.voucher.revoke"


class VoucherServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def mask_voucher_code(value: str | None) -> str:
    """Preserve only the final four characters of a voucher code."""

    if not value:
        return "****"
    normalized = value.strip()
    if len(normalized) <= 4:
        return "*" * len(normalized)
    return "*" * (len(normalized) - 4) + normalized[-4:]


def _raw_code(raw: dict[str, Any]) -> str | None:
    for key in ("code", "voucher_code", "consume_code", "coupon_code"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _voucher_reference(code: str, sku_id: str | None) -> str:
    value = f"{sku_id or ''}\0{code}".encode()
    return "voucher:" + hashlib.sha256(value).hexdigest()


def _request_no(prefix: str, tenant_id: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}\0{idempotency_key}".encode()).hexdigest()
    return f"{prefix}-{digest}"


def _operational_code(voucher: LocalVoucher, settings: Settings | None) -> str:
    if voucher.code_ciphertext:
        if settings is None:
            raise GatewayTerminalError(
                "券码解密配置缺失", code="voucher_decryption_unavailable"
            )
        try:
            value = decrypt_secret_bundle(
                voucher.code_ciphertext, settings.encryption_key
            ).get("code")
        except ValueError as error:
            raise GatewayTerminalError("券码无法解密", code="voucher_decryption_failed") from error
        if isinstance(value, str) and value:
            return value
        raise GatewayTerminalError("券码内容无效", code="voucher_decryption_failed")
    # Legacy/mock rows created before encrypted voucher storage remain operable.
    if voucher.external_voucher_id and not voucher.external_voucher_id.startswith("voucher:"):
        return voucher.external_voucher_id
    raise GatewayTerminalError("券码内容缺失", code="voucher_code_missing")


def _safe_raw(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "status",
        "state",
        "product_id",
        "sku_id",
        "valid_from",
        "valid_until",
        "consume_store_id",
        "consume_store_name",
        "out_store_id",
        "order_id",
        "voucher_type",
        "code_type",
    }
    return {
        key: value
        for key, value in raw.items()
        if key in allowed and not isinstance(value, (dict, list))
    }


def _parse_dt(value: Any) -> datetime | None:
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


class VoucherService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings

    async def _voucher(self, tenant_id: str, voucher_id: str) -> LocalVoucher | None:
        return (
            await self.session.execute(
                select(LocalVoucher).where(
                    LocalVoucher.tenant_id == tenant_id,
                    LocalVoucher.id == voucher_id,
                )
            )
        ).scalar_one_or_none()

    async def list_vouchers(
        self, tenant_id: str, *, order_id: str | None = None
    ) -> list[LocalVoucher]:
        statement = select(LocalVoucher).where(LocalVoucher.tenant_id == tenant_id)
        if order_id is not None:
            statement = statement.where(LocalVoucher.order_id == order_id)
        return list(
            (await self.session.execute(statement.order_by(LocalVoucher.created_at)))
            .scalars()
            .all()
        )

    async def get_voucher(self, tenant_id: str, voucher_id: str) -> LocalVoucher | None:
        return await self._voucher(tenant_id, voucher_id)

    async def upsert_remote_voucher(
        self,
        tenant_id: str,
        connection_id: str,
        result: VoucherResult,
        *,
        order_id: str | None = None,
    ) -> LocalVoucher:
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
            raise VoucherServiceError("connection_not_found", "连接不存在", 404)
        raw = result.raw if isinstance(result.raw, dict) else {}
        raw_code = _raw_code(raw) or result.external_id
        sku_id = _str_or_none(raw.get("sku_id"))
        external_reference = (
            _voucher_reference(raw_code, sku_id)
            if self.settings is not None
            else result.external_id
        )
        voucher = (
            await self.session.execute(
                select(LocalVoucher).where(
                    LocalVoucher.tenant_id == tenant_id,
                    LocalVoucher.connection_id == connection_id,
                    LocalVoucher.external_voucher_id.in_(
                        {external_reference, result.external_id}
                    ),
                )
            )
        ).scalar_one_or_none()
        if voucher is None:
            voucher = LocalVoucher(
                tenant_id=tenant_id,
                connection_id=connection_id,
                order_id=order_id,
                external_voucher_id=external_reference,
            )
            self.session.add(voucher)
        elif order_id is not None:
            voucher.order_id = order_id
        voucher.external_voucher_id = external_reference
        if self.settings is not None and raw_code:
            voucher.code_ciphertext = encrypt_secret_bundle(
                {"code": raw_code}, self.settings.encryption_key
            )
        voucher.external_product_id = result.product_id or _str_or_none(raw.get("product_id"))
        voucher.external_sku_id = sku_id
        voucher.code_masked = mask_voucher_code(raw_code)
        voucher.state = result.state
        voucher.consume_store_id = result.consume_store_id or _str_or_none(
            raw.get("consume_store_id")
        )
        voucher.valid_from = _parse_dt(raw.get("valid_from", raw.get("start_time")))
        voucher.valid_until = _parse_dt(raw.get("valid_until", raw.get("end_time")))
        if result.state == "consumed" and voucher.consumed_at is None:
            voucher.consumed_at = utcnow()
        if result.state != "consumed":
            voucher.consumed_at = None
        if (
            result.state == "available"
            and voucher.revoked_at is None
            and voucher.consume_store_id is None
        ):
            voucher.revoked_at = None
        voucher.raw_summary = _safe_raw(raw)
        voucher.last_synced_at = utcnow()
        await self.session.flush()
        return voucher

    async def _mapped_store(self, tenant_id: str, store_id: str) -> Store:
        store = (
            await self.session.execute(
                select(Store)
                .join(
                    StorePoiMapping,
                    StorePoiMapping.store_id == Store.id,
                )
                .where(
                    Store.tenant_id == tenant_id,
                    Store.id == store_id,
                    Store.status == "active",
                    StorePoiMapping.tenant_id == tenant_id,
                    StorePoiMapping.state == "active",
                )
            )
        ).scalar_one_or_none()
        if store is None:
            raise VoucherServiceError(
                "store_mapping_required", "消费门店必须存在已确认的有效映射", 409
            )
        return store

    async def enqueue_consume(
        self,
        tenant_id: str,
        voucher_id: str,
        store_id: str,
        idempotency_key: str,
        reserve_no: str | None = None,
    ) -> IntegrationOperation:
        operation_service = OperationService(self.session)
        existing = await operation_service.get_by_idempotency_key(tenant_id, idempotency_key)
        if existing is not None:
            if (
                existing.command_type != CONSUME_VOUCHER_COMMAND
                or existing.payload.get("voucher_id") != voucher_id
                or existing.payload.get("store_id") != store_id
                or existing.payload.get("reserve_no") != reserve_no
            ):
                raise VoucherServiceError(
                    "idempotency_key_conflict", "幂等键已用于其他操作", 409
                )
            return existing
        voucher = await self._voucher(tenant_id, voucher_id)
        if voucher is None:
            raise VoucherServiceError("voucher_not_found", "券码不存在", 404)
        if voucher.state != "available":
            raise VoucherServiceError("voucher_state", "券码当前不可核销", 409)
        store = await self._mapped_store(tenant_id, store_id)
        if not voucher.external_sku_id:
            raise VoucherServiceError("voucher_sku_missing", "券码缺少微信 SKU 标识", 409)
        return await operation_service.enqueue(
            tenant_id,
            CONSUME_VOUCHER_COMMAND,
            idempotency_key,
            {
                "entity_id": voucher.id,
                "external_id": voucher.external_voucher_id,
                "voucher_id": voucher.id,
                "external_voucher_id": voucher.external_voucher_id,
                "store_id": store.id,
                "out_store_id": store.code,
                "consume_store_name": store.name,
                "consume_request_no": _request_no("consume", tenant_id, idempotency_key),
                "reserve_no": reserve_no,
            },
            connection_id=voucher.connection_id,
            resource_ref=f"local_voucher:{voucher.id}",
        )

    async def enqueue_revoke(
        self,
        tenant_id: str,
        voucher_id: str,
        idempotency_key: str,
        *,
        store_id: str | None = None,
    ) -> IntegrationOperation:
        operation_service = OperationService(self.session)
        existing = await operation_service.get_by_idempotency_key(tenant_id, idempotency_key)
        if existing is not None:
            if (
                existing.command_type != REVOKE_VOUCHER_COMMAND
                or existing.payload.get("voucher_id") != voucher_id
                or existing.payload.get("store_id") != store_id
            ):
                raise VoucherServiceError(
                    "idempotency_key_conflict", "幂等键已用于其他操作", 409
                )
            return existing
        voucher = await self._voucher(tenant_id, voucher_id)
        if voucher is None:
            raise VoucherServiceError("voucher_not_found", "券码不存在", 404)
        if voucher.state != "consumed":
            raise VoucherServiceError("voucher_state", "券码当前未核销", 409)
        out_store_id = voucher.consume_store_id
        if store_id is not None:
            out_store_id = (await self._mapped_store(tenant_id, store_id)).code
        return await operation_service.enqueue(
            tenant_id,
            REVOKE_VOUCHER_COMMAND,
            idempotency_key,
            {
                "entity_id": voucher.id,
                "external_id": voucher.external_voucher_id,
                "voucher_id": voucher.id,
                "external_voucher_id": voucher.external_voucher_id,
                "store_id": store_id,
                "out_store_id": out_store_id,
                "revoke_request_no": _request_no("revoke", tenant_id, idempotency_key),
                "consume_request_no": voucher.last_consume_request_no,
            },
            connection_id=voucher.connection_id,
            resource_ref=f"local_voucher:{voucher.id}",
        )


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def voucher_operation_handlers(
    session: AsyncSession,
    settings: Settings | None = None,
    *,
    gateway_override: LocalLifeGateway | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Handler]:
    service = VoucherService(session, settings=settings)

    async def gateway_for(operation: IntegrationOperation, connection_id: str) -> LocalLifeGateway:
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

    async def apply_remote(voucher: LocalVoucher, result: VoucherResult) -> None:
        voucher.state = result.state
        voucher.consume_store_id = result.consume_store_id
        if result.state == "consumed":
            voucher.consumed_at = voucher.consumed_at or utcnow()
            voucher.revoked_at = None
        elif result.state == "available":
            voucher.revoked_at = utcnow()
            voucher.consumed_at = None
        voucher.raw_summary = _safe_raw(result.raw if isinstance(result.raw, dict) else {})
        voucher.last_synced_at = utcnow()

    async def consume(operation: IntegrationOperation) -> dict[str, Any]:
        voucher_id = operation.payload.get("entity_id", operation.payload.get("voucher_id"))
        out_store_id = operation.payload.get("out_store_id")
        consume_request_no = operation.payload.get("consume_request_no")
        if (
            not isinstance(voucher_id, str)
            or not isinstance(out_store_id, str)
            or not isinstance(consume_request_no, str)
        ):
            raise GatewayTerminalError("核销操作参数无效", code="invalid_operation_payload")
        voucher = await service._voucher(operation.tenant_id, voucher_id)
        if voucher is None:
            raise GatewayTerminalError("券码不存在", code="voucher_not_found")
        if not voucher.external_sku_id:
            raise GatewayTerminalError("券码缺少微信 SKU 标识", code="voucher_sku_missing")
        gateway = await gateway_for(operation, voucher.connection_id)
        code = _operational_code(voucher, settings)
        try:
            result = await gateway.consume_voucher(
                code,
                sku_id=voucher.external_sku_id,
                consume_request_no=consume_request_no,
                out_store_id=out_store_id,
                consume_store_name=(
                    str(operation.payload["consume_store_name"])
                    if operation.payload.get("consume_store_name")
                    else None
                ),
                consume_channel=2,
                reserve_no=(
                    str(operation.payload["reserve_no"])
                    if operation.payload.get("reserve_no")
                    else None
                ),
            )
        except (GatewayTransientError, TimeoutError) as error:
            if isinstance(error, GatewayTransientError) and error.code not in {
                "timeout",
                "upstream_unavailable",
            }:
                raise
            remote = await gateway.get_voucher(code, sku_id=voucher.external_sku_id)
            if remote.state == "consumed" and (remote.consume_store_id in {None, out_store_id}):
                await apply_remote(voucher, remote)
                voucher.last_consume_request_no = consume_request_no
                await session.commit()
                return {
                    "entity_id": voucher.id,
                    "voucher_id": voucher.id,
                    "state": voucher.state,
                    "reconciled": True,
                }
            raise
        await apply_remote(voucher, result)
        voucher.last_consume_request_no = consume_request_no
        await session.commit()
        return {
            "entity_id": voucher.id,
            "voucher_id": voucher.id,
            "state": voucher.state,
            "reconciled": False,
        }

    async def revoke(operation: IntegrationOperation) -> dict[str, Any]:
        voucher_id = operation.payload.get("entity_id", operation.payload.get("voucher_id"))
        if not isinstance(voucher_id, str):
            raise GatewayTerminalError("撤销操作参数无效", code="invalid_operation_payload")
        voucher = await service._voucher(operation.tenant_id, voucher_id)
        if voucher is None:
            raise GatewayTerminalError("券码不存在", code="voucher_not_found")
        if not voucher.external_sku_id:
            raise GatewayTerminalError("券码缺少微信 SKU 标识", code="voucher_sku_missing")
        gateway = await gateway_for(operation, voucher.connection_id)
        code = _operational_code(voucher, settings)
        revoke_request_no = operation.payload.get("revoke_request_no")
        if not isinstance(revoke_request_no, str):
            raise GatewayTerminalError("撤销操作参数无效", code="invalid_operation_payload")
        consume_request_no = operation.payload.get("consume_request_no")
        try:
            result = await gateway.revoke_consumption(
                code,
                sku_id=voucher.external_sku_id,
                revoke_request_no=revoke_request_no,
                consume_request_no=(
                    consume_request_no if isinstance(consume_request_no, str) else None
                ),
            )
        except (GatewayTransientError, TimeoutError) as error:
            if isinstance(error, GatewayTransientError) and error.code not in {
                "timeout",
                "upstream_unavailable",
            }:
                raise
            remote = await gateway.get_voucher(code, sku_id=voucher.external_sku_id)
            if remote.state == "available":
                await apply_remote(voucher, remote)
                await session.commit()
                return {
                    "entity_id": voucher.id,
                    "voucher_id": voucher.id,
                    "state": voucher.state,
                    "reconciled": True,
                }
            raise
        await apply_remote(voucher, result)
        voucher.last_consume_request_no = None
        await session.commit()
        return {"entity_id": voucher.id, "voucher_id": voucher.id, "state": voucher.state}

    return {CONSUME_VOUCHER_COMMAND: consume, REVOKE_VOUCHER_COMMAND: revoke}


__all__ = [
    "CONSUME_VOUCHER_COMMAND",
    "REVOKE_VOUCHER_COMMAND",
    "VoucherService",
    "VoucherServiceError",
    "mask_voucher_code",
    "voucher_operation_handlers",
]
