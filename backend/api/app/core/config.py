from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_name: str = "Telegram Customer Service Bot API"
    app_env: str = "development"
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
    cors_allow_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=ENV_FILE, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
