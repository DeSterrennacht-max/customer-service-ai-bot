from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.app.core.defaults import DEFAULT_UNANSWERED_FALLBACK_MESSAGE
from backend.api.app.routers import bot_profiles


def test_normalize_unanswered_fallback_message_uses_default_for_blank() -> None:
    assert bot_profiles.normalize_unanswered_fallback_message("   ") == DEFAULT_UNANSWERED_FALLBACK_MESSAGE


def test_sync_telegram_bot_description_skips_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bot_profiles.telegram_service,
        "set_bot_description_sync",
        lambda *args, **kwargs: pytest.fail("Blank description should not call Telegram"),
    )

    synced = bot_profiles.sync_telegram_bot_description(SimpleNamespace(telegram_bot_token="bot-token"), " ")

    assert synced is False


def test_sync_telegram_bot_description_calls_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        bot_profiles.telegram_service,
        "set_bot_description_sync",
        lambda bot_token, description: captured.update({"bot_token": bot_token, "description": description}) or True,
    )

    synced = bot_profiles.sync_telegram_bot_description(SimpleNamespace(telegram_bot_token="bot-token"), " 客服 Bot ")

    assert synced is True
    assert captured == {"bot_token": "bot-token", "description": "客服 Bot"}


def test_sync_telegram_bot_description_raises_when_telegram_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot_profiles.telegram_service, "set_bot_description_sync", lambda *args, **kwargs: False)

    with pytest.raises(HTTPException) as exc_info:
        bot_profiles.sync_telegram_bot_description(SimpleNamespace(telegram_bot_token="bot-token"), "客服 Bot")

    assert exc_info.value.status_code == 502


def test_fetch_telegram_bot_description_returns_current_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot_profiles.telegram_service, "get_bot_description_sync", lambda bot_token: "当前说明")

    description = bot_profiles.fetch_telegram_bot_description(SimpleNamespace(telegram_bot_token="bot-token"))

    assert description == "当前说明"


def test_fetch_telegram_bot_description_rejects_placeholder_token() -> None:
    with pytest.raises(HTTPException) as exc_info:
        bot_profiles.fetch_telegram_bot_description(SimpleNamespace(telegram_bot_token="CHANGE_ME"))

    assert exc_info.value.status_code == 400


def test_fetch_telegram_bot_description_raises_when_telegram_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot_profiles.telegram_service, "get_bot_description_sync", lambda bot_token: None)

    with pytest.raises(HTTPException) as exc_info:
        bot_profiles.fetch_telegram_bot_description(SimpleNamespace(telegram_bot_token="bot-token"))

    assert exc_info.value.status_code == 502
