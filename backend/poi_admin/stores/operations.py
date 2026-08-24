"""Durable operation handlers for remote POI synchronization and commands."""

from __future__ import annotations

from typing import cast

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import (
    Capability,
    GatewayError,
    GatewayTerminalError,
    ServicePoiGateway,
)
from poi_admin.connections.service import ConnectionService
from poi_admin.core.config import Settings
from poi_admin.operations.models import IntegrationOperation
from poi_admin.operations.worker import Handler

from .service import StoreService, StoreServiceError

POI_SYNC_COMMAND = "service_poi.sync"
POI_CREATE_COMMAND = "service_poi.create"
POI_UPDATE_COMMAND = "service_poi.update"
POI_DELETE_COMMAND = "service_poi.delete"
POI_AUDIT_COMMAND = "service_poi.audit_status"


def store_operation_handlers(
    session: AsyncSession,
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Handler]:
    service = StoreService(session)

    async def gateway_for(
        operation: IntegrationOperation,
    ) -> tuple[ServicePoiGateway, WeChatConnection]:
        connection_id = operation.connection_id
        if connection_id is None:
            raise GatewayTerminalError(
                "POI operation connection is missing", code="connection_not_found"
            )
        connection_service = ConnectionService(
            session, settings, http_client=http_client
        )
        connection = await connection_service.get(operation.tenant_id, connection_id)
        if connection is None:
            raise GatewayTerminalError(
                "POI operation connection was not found", code="connection_not_found"
            )
        if connection.capability != Capability.SERVICE_POI.value:
            raise GatewayTerminalError(
                "Connection does not support service POIs", code="invalid_connection"
            )
        return (
            cast(
                ServicePoiGateway,
                await connection_service.gateway(operation.tenant_id, connection.id),
            ),
            connection,
        )

    async def synchronize(operation: IntegrationOperation) -> dict[str, int]:
        gateway, connection = await gateway_for(operation)
        try:
            pois = await service.sync_pois(
                operation.tenant_id,
                connection,
                actor_user_id=str(operation.payload.get("actor_user_id", "system")),
                gateway=gateway,
            )
        except StoreServiceError as error:
            if isinstance(error.__cause__, GatewayError):
                raise error.__cause__
            raise
        candidates = await service.generate_candidates(operation.tenant_id, connection.id)
        return {"poi_count": len(pois), "candidate_count": len(candidates)}

    async def create(operation: IntegrationOperation) -> dict[str, str]:
        gateway, connection = await gateway_for(operation)
        result = await gateway.create_poi(dict(operation.payload))
        poi = await service.save_poi_result(operation.tenant_id, connection, result)
        return {"poi_id": poi.id, "external_poi_id": poi.external_poi_id}

    async def update(operation: IntegrationOperation) -> dict[str, str]:
        gateway, connection = await gateway_for(operation)
        poi_id = operation.payload.get("poi_id")
        if not isinstance(poi_id, str):
            raise GatewayTerminalError(
                "POI operation is missing poi_id", code="invalid_operation_payload"
            )
        poi = await service.get_poi(operation.tenant_id, poi_id)
        if poi is None or poi.connection_id != connection.id:
            raise GatewayTerminalError("POI was not found", code="poi_not_found")
        payload = {
            key: value
            for key, value in operation.payload.items()
            if key not in {"poi_id", "idempotency_key"} and value is not None
        }
        result = await gateway.update_poi(poi.external_poi_id, payload)
        saved = await service.save_poi_result(operation.tenant_id, connection, result)
        return {"poi_id": saved.id, "external_poi_id": saved.external_poi_id}

    async def delete(operation: IntegrationOperation) -> dict[str, str]:
        gateway, connection = await gateway_for(operation)
        poi_id = operation.payload.get("poi_id")
        if not isinstance(poi_id, str):
            raise GatewayTerminalError(
                "POI operation is missing poi_id", code="invalid_operation_payload"
            )
        poi = await service.get_poi(operation.tenant_id, poi_id)
        if poi is None or poi.connection_id != connection.id:
            raise GatewayTerminalError("POI was not found", code="poi_not_found")
        try:
            await gateway.delete_poi(poi.external_poi_id)
        except GatewayTerminalError as error:
            if error.code != "poi_not_found":
                raise
        poi.remote_status = "deleted"
        from .models import utcnow

        poi.last_synced_at = utcnow()
        await session.commit()
        return {"poi_id": poi.id, "external_poi_id": poi.external_poi_id}

    async def audit_status(operation: IntegrationOperation) -> dict[str, str]:
        gateway, connection = await gateway_for(operation)
        poi_id = operation.payload.get("poi_id")
        if not isinstance(poi_id, str):
            raise GatewayTerminalError(
                "POI operation is missing poi_id", code="invalid_operation_payload"
            )
        poi = await service.get_poi(operation.tenant_id, poi_id)
        if poi is None or poi.connection_id != connection.id:
            raise GatewayTerminalError("POI was not found", code="poi_not_found")
        poi.remote_status = await gateway.get_audit_status(poi.external_poi_id)
        from .models import utcnow

        poi.last_synced_at = utcnow()
        await session.commit()
        return {"poi_id": poi.id, "status": poi.remote_status}

    return {
        POI_SYNC_COMMAND: synchronize,
        POI_CREATE_COMMAND: create,
        POI_UPDATE_COMMAND: update,
        POI_DELETE_COMMAND: delete,
        POI_AUDIT_COMMAND: audit_status,
    }


__all__ = [
    "POI_AUDIT_COMMAND",
    "POI_CREATE_COMMAND",
    "POI_DELETE_COMMAND",
    "POI_SYNC_COMMAND",
    "POI_UPDATE_COMMAND",
    "store_operation_handlers",
]
