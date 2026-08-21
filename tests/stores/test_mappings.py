from __future__ import annotations

import pytest
from sqlalchemy import select

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability, ConnectionMode
from poi_admin.identity.models import Tenant, User
from poi_admin.stores.models import StorePoiMapping
from poi_admin.stores.service import StoreService, StoreServiceError


@pytest.mark.asyncio
async def test_candidates_require_explicit_human_confirmation(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        actor = (
            await session.execute(select(User).where(User.email == "operator@example.com"))
        ).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.SERVICE_POI.value,
            mode=ConnectionMode.MOCK.value,
        )
        session.add(connection)
        await session.commit()
        service = StoreService(session)
        await service.create_store(
            tenant.id,
            code="HZ-XH-01",
            name="西湖门店",
            address="杭州市西湖区孤山路1号",
            latitude=30.25,
            longitude=120.16,
        )
        pois = await service.sync_pois(tenant.id, connection, actor_user_id=actor.id)
        candidates = await service.generate_candidates(tenant.id, connection.id)

        mappings_before = await service.list_mappings(tenant.id)
        assert pois
        assert candidates
        assert mappings_before == []

        mapping = await service.confirm_candidate(tenant.id, candidates[0].id, actor.id)

        assert mapping.state == "active"
        assert mapping.confirmed_by_user_id == actor.id
        assert mapping.match_evidence["source"] == "candidate"


@pytest.mark.asyncio
async def test_mapping_constraints_and_tenant_isolation(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        actor = (
            await session.execute(select(User).where(User.is_platform_admin.is_(True)))
        ).scalar_one()
        other_tenant = Tenant(name="其他租户", slug="other-mapping-tenant")
        session.add(other_tenant)
        await session.flush()
        connection = WeChatConnection(
            tenant_id=tenant.id, capability=Capability.SERVICE_POI.value, mode="mock"
        )
        session.add(connection)
        await session.commit()
        service = StoreService(session)
        first = await service.create_store(tenant.id, code="S-1", name="一店", address="地址1")
        second = await service.create_store(tenant.id, code="S-2", name="二店", address="地址2")
        pois = await service.sync_pois(tenant.id, connection, actor_user_id=actor.id)
        poi = pois[0]
        mapping = await service.manual_map(tenant.id, first.id, poi.id, actor.id)

        with pytest.raises(StoreServiceError) as conflict:
            await service.manual_map(tenant.id, second.id, poi.id, actor.id)
        assert conflict.value.code == "mapping_conflict"
        with pytest.raises(StoreServiceError) as store_conflict:
            await service.manual_map(tenant.id, first.id, pois[1].id, actor.id)
        assert store_conflict.value.code == "mapping_conflict"
        assert await service.get_store(other_tenant.id, first.id) is None
        assert await service.list_pois(other_tenant.id) == []
        assert await service.list_mappings(other_tenant.id) == []

        await service.unbind_mapping(tenant.id, mapping.id, actor.id)
        replacement = await service.manual_map(tenant.id, second.id, poi.id, actor.id)
        assert replacement.state == "active"
        history = list(
            (
                await session.execute(
                    select(StorePoiMapping).where(StorePoiMapping.tenant_id == tenant.id)
                )
            ).scalars()
        )
        assert {item.state for item in history} == {"active", "unbound"}


@pytest.mark.asyncio
async def test_poi_sync_classifies_gateway_failures(client) -> None:
    database = client._transport.app.state.database  # type: ignore[attr-defined]
    async with database.session_factory() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == "demo"))).scalar_one()
        actor = (
            await session.execute(select(User).where(User.is_platform_admin.is_(True)))
        ).scalar_one()
        connection = WeChatConnection(
            tenant_id=tenant.id,
            capability=Capability.SERVICE_POI.value,
            mode=ConnectionMode.MOCK.value,
            mock_scenario="rate_limit",
        )
        session.add(connection)
        await session.commit()

        with pytest.raises(StoreServiceError) as failure:
            await StoreService(session).sync_pois(
                tenant.id, connection, actor_user_id=actor.id
            )

        assert failure.value.code == "rate_limited"
        assert failure.value.status_code == 503
