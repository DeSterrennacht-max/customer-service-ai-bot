import pytest
from backend.api.app.core.config import Settings


def test_app_env_and_name_use_documented_environment_variables(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_NAME", "Service")
    settings = Settings(_env_file=None, secret_key="s" * 40, webhook_secret="test", public_base_url="https://example.com",
                        auto_create_schema=False, bootstrap_demo_data=False)
    assert settings.app_env == "production" and settings.app_name == "Service"
    settings.validate_production()


def test_production_startup_rejects_placeholder_secrets():
    settings = Settings(_env_file=None, app_env="production", secret_key="change-me")
    with pytest.raises(ValueError, match="APP_SECRET_KEY"):
        settings.validate_production()
