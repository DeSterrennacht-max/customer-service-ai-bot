from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_name: str = Field(default="Telegram Customer Service Bot API", validation_alias=AliasChoices("APP_NAME", "APP_APP_NAME"))
    app_env: str = Field(default="development", validation_alias=AliasChoices("APP_ENV", "APP_APP_ENV"))
    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/customer_service_bot"
    redis_url: str = "redis://localhost:6379/0"
    auto_create_schema: bool = True
    bootstrap_demo_data: bool = True
    default_tenant_name: str = "Default Tenant"
    default_bot_name: str = "Support Bot"
    default_support_group_chat_id: str | None = None
    default_admin_email: str = "admin@example.com"
    default_admin_password: str = "ChangeMe123!"
    default_super_admin_email: str = "superadmin@example.com"
    default_super_admin_password: str = "ChangeMe123!"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    router_model: str = "gpt-4o-mini"
    generator_model: str = "gpt-4.1-mini"
    webhook_secret: str | None = Field(default=None)
    public_base_url: str | None = None
    object_storage_endpoint_url: str | None = None
    object_storage_access_key_id: str | None = None
    object_storage_secret_access_key: str | None = None
    object_storage_bucket: str | None = None
    object_storage_public_base_url: str | None = None
    object_storage_max_image_bytes: int = 5 * 1024 * 1024
    r2_endpoint_url: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    r2_public_base_url: str | None = None
    r2_max_image_bytes: int = 5 * 1024 * 1024
    cors_allow_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    login_attempt_limit: int = 10
    login_attempt_window_seconds: int = 900
    delivery_max_attempts: int = 5

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=ENV_FILE, extra="ignore", populate_by_name=True)

    def validate_production(self) -> "Settings":
        if self.app_env == "production":
            if len(self.secret_key) < 32 or self.secret_key == "change-me":
                raise ValueError("Production requires APP_SECRET_KEY with at least 32 characters")
            if not self.webhook_secret or not self.public_base_url or not self.public_base_url.startswith("https://"):
                raise ValueError("Production requires APP_WEBHOOK_SECRET and an HTTPS APP_PUBLIC_BASE_URL")
            if self.auto_create_schema or self.bootstrap_demo_data:
                raise ValueError("Production requires migrations and disabled demo bootstrap")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
