import pytest
from scripts.provision_additional_platform_admin import (
    ProvisioningError,
    create_additional_admin,
)
from sqlalchemy import select

from poi_admin.identity.models import User


async def test_additional_admin_requires_confirmation_and_preserves_existing_user(client):
    async with client._transport.app.state.database.session_factory() as session:
        existing = await session.scalar(select(User).where(User.email == "admin@example.com"))
        original_hash = existing.password_hash
        with pytest.raises(ProvisioningError, match="confirmation"):
            await create_additional_admin(
                session,
                email="additional@example.com",
                password="test-password-only",
                display_name="Additional",
                confirm_global_admin=False,
            )
        user = await create_additional_admin(
            session,
            email="additional@example.com",
            password="test-password-only",
            display_name="Additional",
            confirm_global_admin=True,
        )
        assert user.is_platform_admin and user.status == "active"
        assert existing.password_hash == original_hash
        assert user.id != existing.id


async def test_additional_admin_never_overwrites_existing_account(client):
    async with client._transport.app.state.database.session_factory() as session:
        existing = await session.scalar(select(User).where(User.email == "admin@example.com"))
        original_hash = existing.password_hash
        with pytest.raises(ProvisioningError, match="account_exists"):
            await create_additional_admin(
                session,
                email=existing.email,
                password="different-password",
                display_name="Different",
                confirm_global_admin=True,
            )
        await session.rollback()
        await session.refresh(existing)
        assert existing.password_hash == original_hash
