"""Tenant-scoped store, POI synchronization, and mapping services."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.mock import MockServicePoiGateway
from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import (
    Capability,
    ConnectionMode,
    GatewayError,
    PoiResult,
    ServicePoiGateway,
)

from .matching import MatchInput, score_candidate
from .models import MatchCandidate, ServicePoi, Store, StorePoiMapping, utcnow


class StoreServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def mask_phone(value: str | None) -> str | None:
    if not value:
        return None
    compact = "".join(character for character in value if character.isdigit())
    if not compact:
        return "****"
    return f"****{compact[-4:]}"


def _checksum(result: PoiResult) -> str:
    serialized = json.dumps(
        {
            "poi_id": result.poi_id,
            "name": result.name,
            "address": result.address,
            "latitude": result.latitude,
            "longitude": result.longitude,
            "status": result.status,
            "raw": result.raw,
        },
        ensure_ascii=True,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


class StoreService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_stores(self, tenant_id: str) -> list[Store]:
        return list(
            (
                await self.session.execute(
                    select(Store)
                    .where(Store.tenant_id == tenant_id)
                    .order_by(Store.created_at, Store.id)
                )
            )
            .scalars()
            .all()
        )

    async def get_store(self, tenant_id: str, store_id: str) -> Store | None:
        return (
            await self.session.execute(
                select(Store).where(Store.tenant_id == tenant_id, Store.id == store_id)
            )
        ).scalar_one_or_none()

    async def create_store(
        self,
        tenant_id: str,
        *,
        code: str,
        name: str,
        address: str,
        contact_name: str | None = None,
        contact_phone: str | None = None,
        province: str | None = None,
        city: str | None = None,
        district: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        status: str = "active",
    ) -> Store:
        store = Store(
            tenant_id=tenant_id,
            code=code.strip(),
            name=name.strip(),
            contact_name=contact_name,
            contact_phone_masked=mask_phone(contact_phone),
            province=province,
            city=city,
            district=district,
            address=address.strip(),
            latitude=latitude,
            longitude=longitude,
            status=status,
        )
        self.session.add(store)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise StoreServiceError("store_code_exists", "门店编码已存在", 409) from error
        await self.session.refresh(store)
        return store

    async def update_store(
        self, tenant_id: str, store_id: str, version: int, changes: dict[str, Any]
    ) -> Store:
        store = await self.get_store(tenant_id, store_id)
        if store is None:
            raise StoreServiceError("store_not_found", "门店不存在", 404)
        if store.version != version:
            raise StoreServiceError("version_conflict", "门店已被其他操作更新", 409)
        allowed = {
            "code",
            "name",
            "contact_name",
            "province",
            "city",
            "district",
            "address",
            "latitude",
            "longitude",
            "status",
        }
        values = {
            field: value.strip() if isinstance(value, str) else value
            for field, value in changes.items()
            if field in allowed
        }
        if "contact_phone" in changes:
            values["contact_phone_masked"] = mask_phone(changes["contact_phone"])
        values["version"] = version + 1
        try:
            result = cast(
                CursorResult[Any],
                await self.session.execute(
                    update(Store)
                    .where(
                        Store.tenant_id == tenant_id,
                        Store.id == store_id,
                        Store.version == version,
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )
            )
            if result.rowcount != 1:
                await self.session.rollback()
                raise StoreServiceError("version_conflict", "门店已被其他操作更新", 409)
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if "code" in changes:
                raise StoreServiceError("store_code_exists", "门店编码已存在", 409) from error
            raise StoreServiceError("store_update_invalid", "门店更新无效", 422) from error
        await self.session.refresh(store)
        return store

    async def archive_store(
        self, tenant_id: str, store_id: str, version: int, actor_user_id: str
    ) -> None:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
            update(Store)
            .where(
                Store.tenant_id == tenant_id,
                Store.id == store_id,
                Store.version == version,
            )
            .values(status="inactive", version=version + 1)
            .execution_options(synchronize_session="fetch")
            ),
        )
        if result.rowcount != 1:
            await self.session.rollback()
            if await self.get_store(tenant_id, store_id) is None:
                raise StoreServiceError("store_not_found", "门店不存在", 404)
            raise StoreServiceError("version_conflict", "门店已被其他操作更新", 409)
        await self.session.execute(
            update(StorePoiMapping)
            .where(
                StorePoiMapping.tenant_id == tenant_id,
                StorePoiMapping.store_id == store_id,
                StorePoiMapping.state == "active",
            )
            .values(
                state="unbound",
                unbound_by_user_id=actor_user_id,
                unbound_at=utcnow(),
            )
            .execution_options(synchronize_session="fetch")
        )
        await self.session.commit()

    async def list_pois(
        self, tenant_id: str, connection_id: str | None = None
    ) -> list[ServicePoi]:
        statement = select(ServicePoi).where(ServicePoi.tenant_id == tenant_id)
        if connection_id is not None:
            statement = statement.where(ServicePoi.connection_id == connection_id)
        return list(
            (
                await self.session.execute(
                    statement.order_by(ServicePoi.last_synced_at.desc(), ServicePoi.id)
                )
            )
            .scalars()
            .all()
        )

    async def get_poi(self, tenant_id: str, poi_id: str) -> ServicePoi | None:
        return (
            await self.session.execute(
                select(ServicePoi).where(
                    ServicePoi.tenant_id == tenant_id,
                    ServicePoi.id == poi_id,
                )
            )
        ).scalar_one_or_none()

    async def save_poi_result(
        self, tenant_id: str, connection: WeChatConnection, result: PoiResult
    ) -> ServicePoi:
        if connection.tenant_id != tenant_id:
            raise StoreServiceError("connection_not_found", "连接不存在", 404)
        poi = (
            await self.session.execute(
                select(ServicePoi).where(
                    ServicePoi.tenant_id == tenant_id,
                    ServicePoi.connection_id == connection.id,
                    ServicePoi.external_poi_id == result.poi_id,
                )
            )
        ).scalar_one_or_none()
        if poi is None:
            poi = ServicePoi(
                tenant_id=tenant_id,
                connection_id=connection.id,
                external_poi_id=result.poi_id,
                name=result.name,
                address=result.address,
                remote_status=result.status,
                raw_checksum=_checksum(result),
            )
            self.session.add(poi)
        poi.name = result.name
        poi.address = result.address
        poi.latitude = result.latitude
        poi.longitude = result.longitude
        poi.remote_status = result.status
        poi.category = str(result.raw.get("category")) if result.raw.get("category") else None
        qualification = result.raw.get("qualification_summary")
        poi.qualification_summary = qualification if isinstance(qualification, dict) else None
        poi.raw_checksum = _checksum(result)
        poi.last_synced_at = utcnow()
        await self.session.commit()
        await self.session.refresh(poi)
        return poi

    async def sync_pois(
        self,
        tenant_id: str,
        connection: WeChatConnection,
        *,
        actor_user_id: str,
        gateway: ServicePoiGateway | None = None,
    ) -> list[ServicePoi]:
        del actor_user_id
        if connection.tenant_id != tenant_id:
            raise StoreServiceError("connection_not_found", "连接不存在", 404)
        if connection.capability != Capability.SERVICE_POI.value:
            raise StoreServiceError("invalid_connection", "连接不支持微信 POI", 422)
        resolved_gateway = gateway
        if resolved_gateway is None:
            if connection.mode != ConnectionMode.MOCK.value:
                raise StoreServiceError("live_gateway_required", "真实连接器尚未配置", 503)
            resolved_gateway = MockServicePoiGateway(
                tenant_id, scenario=connection.mock_scenario
            )
        try:
            remote_pois = await resolved_gateway.list_pois()
        except GatewayError as error:
            status_code = 503 if error.retryable else 422
            raise StoreServiceError(error.code, str(error), status_code) from error
        existing_pois = list(
            (
                await self.session.execute(
                    select(ServicePoi).where(
                        ServicePoi.tenant_id == tenant_id,
                        ServicePoi.connection_id == connection.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        remote_ids = {remote.poi_id for remote in remote_pois}
        for stale in existing_pois:
            if (
                stale.external_poi_id not in remote_ids
                and not stale.external_poi_id.startswith(("audit:", "map:"))
            ):
                stale.remote_status = "deleted"
                stale.last_synced_at = utcnow()

        synchronized: list[ServicePoi] = []
        for remote in remote_pois:
            poi = (
                await self.session.execute(
                    select(ServicePoi).where(
                        ServicePoi.tenant_id == tenant_id,
                        ServicePoi.connection_id == connection.id,
                        ServicePoi.external_poi_id == remote.poi_id,
                    )
                )
            ).scalar_one_or_none()
            if poi is None:
                pending_matches = [
                    item
                    for item in existing_pois
                    if item.external_poi_id.startswith("audit:")
                    and item.name.strip().casefold() == remote.name.strip().casefold()
                    and item.address.strip().casefold() == remote.address.strip().casefold()
                ]
                if len(pending_matches) == 1:
                    poi = pending_matches[0]
                    poi.external_poi_id = remote.poi_id
            if poi is None:
                poi = ServicePoi(
                    tenant_id=tenant_id,
                    connection_id=connection.id,
                    external_poi_id=remote.poi_id,
                    name=remote.name,
                    address=remote.address,
                    remote_status=remote.status,
                    raw_checksum=_checksum(remote),
                )
                self.session.add(poi)
            poi.name = remote.name
            poi.address = remote.address
            poi.latitude = remote.latitude
            poi.longitude = remote.longitude
            poi.remote_status = remote.status
            poi.category = str(remote.raw.get("category")) if remote.raw.get("category") else None
            qualification = remote.raw.get("qualification_summary")
            poi.qualification_summary = qualification if isinstance(qualification, dict) else None
            poi.raw_checksum = _checksum(remote)
            poi.last_synced_at = utcnow()
            synchronized.append(poi)
        await self.session.commit()
        for poi in synchronized:
            await self.session.refresh(poi)
        return synchronized

    async def generate_candidates(
        self, tenant_id: str, connection_id: str
    ) -> list[MatchCandidate]:
        stores = list(
            (
                await self.session.execute(
                    select(Store).where(Store.tenant_id == tenant_id, Store.status == "active")
                )
            )
            .scalars()
            .all()
        )
        pois = [
            poi
            for poi in await self.list_pois(tenant_id, connection_id)
            if poi.remote_status not in {"deleted", "stale"}
        ]
        active_mappings = list(
            (
                await self.session.execute(
                    select(StorePoiMapping).where(
                        StorePoiMapping.tenant_id == tenant_id,
                        StorePoiMapping.connection_id == connection_id,
                        StorePoiMapping.state == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        mapped_store_ids = {item.store_id for item in active_mappings}
        mapped_poi_ids = {item.service_poi_id for item in active_mappings}
        existing = list(
            (
                await self.session.execute(
                    select(MatchCandidate).where(
                        MatchCandidate.tenant_id == tenant_id,
                        MatchCandidate.connection_id == connection_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_pair = {(item.store_id, item.service_poi_id): item for item in existing}
        candidates: list[MatchCandidate] = []
        for store in stores:
            if store.id in mapped_store_ids:
                continue
            for poi in pois:
                if poi.id in mapped_poi_ids:
                    continue
                candidate = by_pair.get((store.id, poi.id))
                if candidate is not None and candidate.dismissed_at is not None:
                    continue
                score = score_candidate(
                    MatchInput(store.name, store.address, store.latitude, store.longitude),
                    MatchInput(poi.name, poi.address, poi.latitude, poi.longitude),
                )
                if candidate is None:
                    candidate = MatchCandidate(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        store_id=store.id,
                        service_poi_id=poi.id,
                    )
                    self.session.add(candidate)
                candidate.total_score = score.total
                candidate.name_score = score.name
                candidate.address_score = score.address
                candidate.distance_score = score.distance
                candidate.distance_meters = score.distance_meters
                candidate.evidence = {
                    **score.evidence(),
                    "store_name": store.name,
                    "poi_name": poi.name,
                    "store_address": store.address,
                    "poi_address": poi.address,
                }
                candidate.generated_at = utcnow()
                candidates.append(candidate)
        await self.session.commit()
        candidates.sort(key=lambda item: item.total_score, reverse=True)
        return candidates

    async def list_candidates(
        self, tenant_id: str, *, include_dismissed: bool = False
    ) -> list[MatchCandidate]:
        statement = (
            select(MatchCandidate)
            .join(ServicePoi, ServicePoi.id == MatchCandidate.service_poi_id)
            .where(
                MatchCandidate.tenant_id == tenant_id,
                ServicePoi.remote_status.not_in(["deleted", "stale"]),
            )
        )
        if not include_dismissed:
            statement = statement.where(MatchCandidate.dismissed_at.is_(None))
            active_mapping = select(StorePoiMapping.id).where(
                StorePoiMapping.tenant_id == tenant_id,
                StorePoiMapping.state == "active",
                or_(
                    StorePoiMapping.store_id == MatchCandidate.store_id,
                    StorePoiMapping.service_poi_id == MatchCandidate.service_poi_id,
                ),
            )
            statement = statement.where(~active_mapping.exists())
        return list(
            (
                await self.session.execute(
                    statement.order_by(MatchCandidate.total_score.desc(), MatchCandidate.id)
                )
            )
            .scalars()
            .all()
        )

    async def dismiss_candidate(
        self, tenant_id: str, candidate_id: str, actor_user_id: str
    ) -> MatchCandidate:
        candidate = await self._candidate(tenant_id, candidate_id)
        candidate.dismissed_at = utcnow()
        candidate.dismissed_by_user_id = actor_user_id
        await self.session.commit()
        await self.session.refresh(candidate)
        return candidate

    async def confirm_candidate(
        self, tenant_id: str, candidate_id: str, actor_user_id: str
    ) -> StorePoiMapping:
        candidate = await self._candidate(tenant_id, candidate_id)
        if candidate.dismissed_at is not None:
            raise StoreServiceError("candidate_dismissed", "候选已被忽略", 409)
        return await self._create_mapping(
            tenant_id,
            candidate.store_id,
            candidate.service_poi_id,
            actor_user_id,
            match_score=candidate.total_score,
            evidence={"source": "candidate", **candidate.evidence},
        )

    async def manual_map(
        self, tenant_id: str, store_id: str, service_poi_id: str, actor_user_id: str
    ) -> StorePoiMapping:
        return await self._create_mapping(
            tenant_id,
            store_id,
            service_poi_id,
            actor_user_id,
            match_score=None,
            evidence={"source": "manual"},
        )

    async def _create_mapping(
        self,
        tenant_id: str,
        store_id: str,
        service_poi_id: str,
        actor_user_id: str,
        *,
        match_score: float | None,
        evidence: dict[str, Any],
    ) -> StorePoiMapping:
        store = await self.get_store(tenant_id, store_id)
        poi = (
            await self.session.execute(
                select(ServicePoi).where(
                    ServicePoi.tenant_id == tenant_id, ServicePoi.id == service_poi_id
                )
            )
        ).scalar_one_or_none()
        if store is None or poi is None:
            raise StoreServiceError("mapping_resource_not_found", "门店或 POI 不存在", 404)
        conflict = (
            await self.session.execute(
                select(StorePoiMapping).where(
                    StorePoiMapping.tenant_id == tenant_id,
                    StorePoiMapping.connection_id == poi.connection_id,
                    StorePoiMapping.state == "active",
                    or_(
                        StorePoiMapping.store_id == store_id,
                        StorePoiMapping.service_poi_id == service_poi_id,
                    ),
                ).limit(1)
            )
        ).scalars().first()
        if conflict is not None:
            if conflict.store_id == store_id and conflict.service_poi_id == service_poi_id:
                return conflict
            raise StoreServiceError("mapping_conflict", "门店或 POI 已存在活动映射", 409)
        mapping = StorePoiMapping(
            tenant_id=tenant_id,
            connection_id=poi.connection_id,
            store_id=store_id,
            service_poi_id=service_poi_id,
            match_score=match_score,
            match_evidence=evidence,
            confirmed_by_user_id=actor_user_id,
        )
        self.session.add(mapping)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise StoreServiceError("mapping_conflict", "门店或 POI 已存在活动映射", 409) from error
        await self.session.refresh(mapping)
        return mapping

    async def list_mappings(
        self, tenant_id: str, *, include_history: bool = False
    ) -> list[StorePoiMapping]:
        statement = select(StorePoiMapping).where(StorePoiMapping.tenant_id == tenant_id)
        if not include_history:
            statement = statement.where(StorePoiMapping.state == "active")
        return list(
            (
                await self.session.execute(
                    statement.order_by(StorePoiMapping.confirmed_at.desc(), StorePoiMapping.id)
                )
            )
            .scalars()
            .all()
        )

    async def unbind_mapping(
        self, tenant_id: str, mapping_id: str, actor_user_id: str
    ) -> StorePoiMapping:
        mapping = (
            await self.session.execute(
                select(StorePoiMapping).where(
                    StorePoiMapping.tenant_id == tenant_id,
                    StorePoiMapping.id == mapping_id,
                    StorePoiMapping.state == "active",
                )
            )
        ).scalar_one_or_none()
        if mapping is None:
            raise StoreServiceError("mapping_not_found", "活动映射不存在", 404)
        mapping.state = "unbound"
        mapping.unbound_by_user_id = actor_user_id
        mapping.unbound_at = utcnow()
        await self.session.commit()
        await self.session.refresh(mapping)
        return mapping

    async def _candidate(self, tenant_id: str, candidate_id: str) -> MatchCandidate:
        candidate = (
            await self.session.execute(
                select(MatchCandidate).where(
                    MatchCandidate.tenant_id == tenant_id, MatchCandidate.id == candidate_id
                )
            )
        ).scalar_one_or_none()
        if candidate is None:
            raise StoreServiceError("candidate_not_found", "匹配候选不存在", 404)
        return candidate


__all__ = ["StoreService", "StoreServiceError", "mask_phone"]
