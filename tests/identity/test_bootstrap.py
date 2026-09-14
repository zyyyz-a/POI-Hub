from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from poi_admin.bootstrap import BootstrapError, bootstrap_platform_admin
from poi_admin.core.database import create_database
from poi_admin.core.orm import Base
from poi_admin.core.security import hash_password, hash_token, utcnow, verify_password
from poi_admin.identity.models import User, UserSession


@pytest.mark.asyncio
async def test_bootstrap_creates_only_first_platform_admin(test_settings) -> None:
    database = create_database(test_settings)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.session_factory() as session:
            result = await bootstrap_platform_admin(
                session,
                email="Owner@Example.com",
                display_name="Owner",
                password="a-strong-bootstrap-password",
            )
            user = (
                await session.execute(select(User).where(User.email == "owner@example.com"))
            ).scalar_one()
            assert result.action == "created"
            assert user.is_platform_admin is True
            assert verify_password(user.password_hash, "a-strong-bootstrap-password")

            with pytest.raises(BootstrapError, match="already exists"):
                await bootstrap_platform_admin(
                    session,
                    email="second@example.com",
                    display_name="Second",
                    password="another-strong-bootstrap-password",
                )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_bootstrap_requires_explicit_promotion(test_settings) -> None:
    database = create_database(test_settings)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.session_factory() as session:
            user = User(
                email="operator@example.com",
                display_name="Operator",
                password_hash=hash_password("original-password"),
            )
            user_email = user.email
            session.add(user)
            await session.commit()

            with pytest.raises(BootstrapError, match="--promote-existing"):
                await bootstrap_platform_admin(
                    session,
                    email=user_email,
                    display_name="Owner",
                    password="a-strong-bootstrap-password",
                )

            result = await bootstrap_platform_admin(
                session,
                email=user_email,
                display_name="Owner",
                password="a-strong-bootstrap-password",
                promote_existing=True,
            )
            await session.refresh(user)
            assert result.action == "promoted"
            assert user.is_platform_admin is True
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_rotate_existing_admin_revokes_sessions(test_settings) -> None:
    database = create_database(test_settings)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.session_factory() as session:
            created = await bootstrap_platform_admin(
                session,
                email="owner@example.com",
                display_name="Owner",
                password="a-strong-bootstrap-password",
            )
            auth_session = UserSession(
                user_id=created.user_id,
                token_hash=hash_token("session-token"),
                csrf_token_hash=hash_token("csrf-token"),
                expires_at=utcnow() + timedelta(hours=1),
            )
            session.add(auth_session)
            await session.commit()

            result = await bootstrap_platform_admin(
                session,
                email="owner@example.com",
                display_name="Recovered Owner",
                password="a-new-strong-bootstrap-password",
                rotate_existing=True,
            )
            user = await session.get(User, created.user_id)
            await session.refresh(auth_session)
            assert result.action == "rotated"
            assert user is not None
            assert user.display_name == "Recovered Owner"
            assert verify_password(user.password_hash, "a-new-strong-bootstrap-password")
            assert auth_session.revoked_at is not None
    finally:
        await database.dispose()


def test_bootstrap_rejects_short_password() -> None:
    from poi_admin.bootstrap import validate_bootstrap_password

    with pytest.raises(BootstrapError, match="at least 16"):
        validate_bootstrap_password("too-short")
