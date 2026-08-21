"""Durable operation handlers for remote POI synchronization."""

from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

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


def store_operation_handlers(
    session: AsyncSession, settings: Settings
) -> dict[str, Handler]:
    async def synchronize(operation: IntegrationOperation) -> dict[str, int]:
        connection_id = operation.connection_id
        if connection_id is None:
            raise GatewayTerminalError(
                "POI sync connection is missing", code="connection_not_found"
            )
        connection_service = ConnectionService(session, settings)
        connection = await connection_service.get(operation.tenant_id, connection_id)
        if connection is None:
            raise GatewayTerminalError(
                "POI sync connection was not found", code="connection_not_found"
            )
        if connection.capability != Capability.SERVICE_POI.value:
            raise GatewayTerminalError(
                "Connection does not support service POIs", code="invalid_connection"
            )
        gateway = cast(
            ServicePoiGateway,
            await connection_service.gateway(operation.tenant_id, connection.id),
        )
        service = StoreService(session)
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

    return {POI_SYNC_COMMAND: synchronize}


__all__ = ["POI_SYNC_COMMAND", "store_operation_handlers"]
