"""Typed, immutable application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
