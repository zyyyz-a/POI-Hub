"""Typed, immutable application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / ".data"
DEFAULT_DATABASE_PATH = DEFAULT_DATA_DIR / "poi_admin.sqlite3"
DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    app_name: str = Field(default="POI Hub", validation_alias=AliasChoices("APP_NAME", "app_name"))
    app_version: str = Field(
        default="0.1.0",
        validation_alias=AliasChoices("APP_VERSION", "app_version"),
    )
    environment: Literal["local", "test", "staging", "production"] = Field(
        default="local",
        validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT", "app_env", "environment"),
    )
    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    secret_key: str = Field(
        default="local-development-only-change-me",
        validation_alias=AliasChoices("SECRET_KEY", "APP_SECRET_KEY", "secret_key"),
    )
    encryption_key: str = Field(
        default="local-development-only-change-me",
        validation_alias=AliasChoices(
            "ENCRYPTION_KEY",
            "ENCRYPTION_MASTER_KEY",
            "encryption_master_key",
            "encryption_key",
        ),
    )
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "log_level"))
    wechat_api_base_url: str = Field(
        default="https://api.weixin.qq.com",
        validation_alias=AliasChoices("WECHAT_API_BASE_URL", "wechat_api_base_url"),
    )
    deployment_mode: Literal["appliance", "saas"] = Field(
        default="saas",
        validation_alias=AliasChoices("DEPLOYMENT_MODE", "deployment_mode"),
    )
    installation_id: str = Field(
        default="local-development",
        min_length=1,
        max_length=120,
        validation_alias=AliasChoices("INSTALLATION_ID", "installation_id"),
    )
    license_mode: Literal["off", "warn", "enforce"] = Field(
        default="off",
        validation_alias=AliasChoices("LICENSE_MODE", "license_mode"),
    )
    license_path: Path = Field(
        default=PROJECT_ROOT / ".data" / "license.json",
        validation_alias=AliasChoices("LICENSE_PATH", "license_path"),
    )
    license_public_key: str = Field(
        default="",
        validation_alias=AliasChoices("LICENSE_PUBLIC_KEY", "license_public_key"),
    )
    allow_sqlite_production: bool = Field(
        default=False,
        validation_alias=AliasChoices("ALLOW_SQLITE_PRODUCTION", "allow_sqlite_production"),
    )
    sqlite_busy_timeout_ms: int = Field(
        default=10_000,
        ge=1_000,
        le=120_000,
        validation_alias=AliasChoices("SQLITE_BUSY_TIMEOUT_MS", "sqlite_busy_timeout_ms"),
    )
    worker_concurrency: int = Field(
        default=1,
        ge=1,
        le=64,
        validation_alias=AliasChoices("WORKER_CONCURRENCY", "worker_concurrency"),
    )
    worker_burst_size: int = Field(
        default=100,
        ge=1,
        le=10_000,
        validation_alias=AliasChoices("WORKER_BURST_SIZE", "worker_burst_size"),
    )
    worker_lease_seconds: int = Field(
        default=120,
        ge=30,
        le=3_600,
        validation_alias=AliasChoices("WORKER_LEASE_SECONDS", "worker_lease_seconds"),
    )
    webhook_max_attempts: int = Field(
        default=8,
        ge=1,
        le=100,
        validation_alias=AliasChoices("WEBHOOK_MAX_ATTEMPTS", "webhook_max_attempts"),
    )
    wechat_http_max_connections: int = Field(
        default=100,
        ge=1,
        le=1_000,
        validation_alias=AliasChoices(
            "WECHAT_HTTP_MAX_CONNECTIONS", "wechat_http_max_connections"
        ),
    )
    wechat_http_max_keepalive_connections: int = Field(
        default=20,
        ge=0,
        le=1_000,
        validation_alias=AliasChoices(
            "WECHAT_HTTP_MAX_KEEPALIVE_CONNECTIONS",
            "wechat_http_max_keepalive_connections",
        ),
    )

    @property
    def app_env(self) -> str:
        """Compatibility alias used by deployment tooling."""

        return self.environment

    @property
    def encryption_master_key(self) -> str:
        """Compatibility alias for code that calls the key a master key."""

        return self.encryption_key

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.wechat_http_max_keepalive_connections > self.wechat_http_max_connections:
            raise ValueError(
                "WECHAT_HTTP_MAX_KEEPALIVE_CONNECTIONS cannot exceed "
                "WECHAT_HTTP_MAX_CONNECTIONS"
            )
        parsed_wechat_url = urlparse(self.wechat_api_base_url)
        if not parsed_wechat_url.hostname or parsed_wechat_url.username:
            raise ValueError("WECHAT_API_BASE_URL must be an absolute URL without credentials")
        if self.environment in {"staging", "production"} and (
            parsed_wechat_url.scheme != "https"
            or parsed_wechat_url.hostname.casefold() != "api.weixin.qq.com"
            or parsed_wechat_url.port not in {None, 443}
        ):
            raise ValueError(
                "WECHAT_API_BASE_URL must use the official WeChat HTTPS host outside local/test"
            )
        if self.deployment_mode == "saas" and self.license_mode != "off":
            raise ValueError(
                "Central SaaS must use tenant subscription controls; "
                "offline LICENSE_MODE is only supported for legacy appliance deployments"
            )
        if self.environment == "production":
            development_values = {
                "",
                "local-development-only-change-me",
                "replace-me-in-production",
            }
            if self.secret_key in development_values or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be a strong production secret")
            if self.encryption_key in development_values or len(self.encryption_key) < 32:
                raise ValueError("ENCRYPTION_KEY must be a strong production secret")
            if self.deployment_mode == "saas" and self.database_url.casefold().startswith(
                "sqlite"
            ):
                raise ValueError(
                    "Central SaaS production requires PostgreSQL; SQLite cannot provide "
                    "the required multi-worker availability and isolation"
                )
        if self.database_url.casefold().startswith("sqlite") and self.worker_concurrency != 1:
            raise ValueError("SQLite deployments require WORKER_CONCURRENCY=1")
        if self.license_mode == "enforce" and not self.license_public_key.strip():
            raise ValueError("LICENSE_PUBLIC_KEY is required when LICENSE_MODE=enforce")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""

    return Settings()


__all__ = [
    "DEFAULT_DATABASE_PATH",
    "DEFAULT_DATABASE_URL",
    "DEFAULT_DATA_DIR",
    "PROJECT_ROOT",
    "Settings",
    "get_settings",
]
