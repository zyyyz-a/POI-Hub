import pytest
from pydantic import ValidationError

from poi_admin.core.config import Settings


def test_saas_production_sqlite_is_always_rejected() -> None:
    with pytest.raises(ValidationError, match="requires PostgreSQL"):
        Settings(
            environment="production",
            deployment_mode="saas",
            database_url="sqlite+aiosqlite:///production.sqlite3",
            secret_key="s" * 40,
            encryption_key="e" * 40,
            allow_sqlite_production=True,
        )


def test_production_postgresql_is_scale_ready_by_default() -> None:
    settings = Settings(
        environment="production",
        deployment_mode="saas",
        database_url="postgresql+asyncpg://app:secret@db/poi",
        secret_key="s" * 40,
        encryption_key="e" * 40,
        worker_concurrency=8,
    )

    assert settings.worker_concurrency == 8


def test_central_saas_is_the_default_deployment_mode() -> None:
    assert Settings().deployment_mode == "saas"


def test_central_saas_rejects_device_license_modes() -> None:
    with pytest.raises(ValidationError, match="tenant subscription controls"):
        Settings(license_mode="enforce", license_public_key="public-key")


def test_local_customer_appliance_allows_production_sqlite_with_one_worker() -> None:
    settings = Settings(
        environment="production",
        deployment_mode="appliance",
        database_url="sqlite+aiosqlite:///customer.sqlite3",
        secret_key="s" * 40,
        encryption_key="e" * 40,
    )

    assert settings.deployment_mode == "appliance"
    assert settings.worker_concurrency == 1


def test_production_rejects_tenant_style_internal_wechat_target() -> None:
    with pytest.raises(ValidationError, match="official WeChat HTTPS host"):
        Settings(
            environment="production",
            database_url="postgresql+asyncpg://app:secret@db/poi",
            secret_key="s" * 40,
            encryption_key="e" * 40,
            wechat_api_base_url="http://169.254.169.254/latest/meta-data",
        )
