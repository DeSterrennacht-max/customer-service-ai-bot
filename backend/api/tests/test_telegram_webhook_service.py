from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.api.app.core.config import Settings
from backend.api.app.services.telegram_webhook_service import TelegramWebhookRegistrationError, TelegramWebhookService


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_register_bot_profile_webhook_uses_username_and_secret() -> None:
    captured: dict = {}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["timeout"] = kwargs["timeout"]
        return FakeResponse({"ok": True, "description": "Webhook was set"})

    bot_profile = SimpleNamespace(
        id=uuid4(),
        telegram_bot_token="123456:token",
        telegram_bot_username="@support_bot",
        is_active=True,
    )
    settings = Settings(app_env="production", public_base_url="https://bot.example.com/", webhook_secret="secret-token")

    result = TelegramWebhookService(settings=settings, post=fake_post).register_bot_profile_webhook(bot_profile)

    assert result is not None
    assert result.url == "https://bot.example.com/telegram/webhook/support_bot"
    assert captured["url"] == "https://api.telegram.org/bot123456:token/setWebhook"
    assert captured["json"] == {
        "url": "https://bot.example.com/telegram/webhook/support_bot",
        "secret_token": "secret-token",
    }
    assert captured["timeout"] == 20


def test_register_bot_profile_webhook_falls_back_to_next_public_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    bot_id = uuid4()

    def fake_post(url: str, **kwargs):
        captured["json"] = kwargs["json"]
        return FakeResponse({"ok": True})

    monkeypatch.setenv("NEXT_PUBLIC_API_BASE_URL", "https://customer-service-admin.example.com")
    bot_profile = SimpleNamespace(
        id=bot_id,
        telegram_bot_token="123456:token",
        telegram_bot_username=None,
        is_active=True,
    )
    settings = Settings(app_env="production", public_base_url=None, webhook_secret=None)

    result = TelegramWebhookService(settings=settings, post=fake_post).register_bot_profile_webhook(bot_profile)

    assert result is not None
    assert result.url == f"https://customer-service-admin.example.com/telegram/webhook/{bot_id}"
    assert captured["json"] == {"url": f"https://customer-service-admin.example.com/telegram/webhook/{bot_id}"}


def test_register_bot_profile_webhook_skips_inactive_bot() -> None:
    def fake_post(*args, **kwargs):
        pytest.fail("inactive bot should not call Telegram")

    bot_profile = SimpleNamespace(
        id=uuid4(),
        telegram_bot_token="123456:token",
        telegram_bot_username="support_bot",
        is_active=False,
    )
    settings = Settings(app_env="production", public_base_url="https://bot.example.com")

    assert TelegramWebhookService(settings=settings, post=fake_post).register_bot_profile_webhook(bot_profile) is None


def test_register_bot_profile_webhook_raises_when_telegram_rejects() -> None:
    def fake_post(*args, **kwargs):
        return FakeResponse({"ok": False, "error_code": 401, "description": "Unauthorized"})

    bot_profile = SimpleNamespace(
        id=uuid4(),
        telegram_bot_token="bad-token",
        telegram_bot_username="support_bot",
        is_active=True,
    )
    settings = Settings(app_env="production", public_base_url="https://bot.example.com")

    with pytest.raises(TelegramWebhookRegistrationError) as exc_info:
        TelegramWebhookService(settings=settings, post=fake_post).register_bot_profile_webhook(bot_profile)

    assert exc_info.value.status_code == 400
    assert "Unauthorized" in str(exc_info.value)


def test_unregister_bot_profile_webhook_calls_delete_webhook() -> None:
    captured: dict = {}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["timeout"] = kwargs["timeout"]
        return FakeResponse({"ok": True, "description": "Webhook was deleted"})

    bot_profile = SimpleNamespace(
        id=uuid4(),
        telegram_bot_token="123456:token",
        telegram_bot_username="support_bot",
        is_active=True,
    )
    settings = Settings(app_env="production", public_base_url="https://bot.example.com")

    result = TelegramWebhookService(settings=settings, post=fake_post).unregister_bot_profile_webhook(bot_profile)

    assert result == "Webhook was deleted"
    assert captured["url"] == "https://api.telegram.org/bot123456:token/deleteWebhook"
    assert captured["json"] == {"drop_pending_updates": True}
    assert captured["timeout"] == 20


def test_unregister_bot_profile_webhook_skips_placeholder_token() -> None:
    def fake_post(*args, **kwargs):
        pytest.fail("placeholder token should not call Telegram")

    bot_profile = SimpleNamespace(
        id=uuid4(),
        telegram_bot_token="CHANGE_ME",
        telegram_bot_username="support_bot",
        is_active=True,
    )
    settings = Settings(app_env="production", public_base_url="https://bot.example.com")

    assert TelegramWebhookService(settings=settings, post=fake_post).unregister_bot_profile_webhook(bot_profile) is None
