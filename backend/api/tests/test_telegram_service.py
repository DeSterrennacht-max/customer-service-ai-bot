from __future__ import annotations

from types import SimpleNamespace

from backend.api.app.services import telegram_service as telegram_service_module
from backend.api.app.services.telegram_service import TelegramService


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBot:
    captured: dict = {}

    def __init__(self, token: str) -> None:
        self.token = token
        self.session = FakeSession()
        FakeBot.captured["token"] = token
        FakeBot.captured["session"] = self.session

    async def send_message(self, **kwargs):
        FakeBot.captured["send_message"] = kwargs
        return SimpleNamespace(message_id=12345)

    async def send_chat_action(self, **kwargs):
        FakeBot.captured["send_chat_action"] = kwargs
        return True

    async def set_my_description(self, **kwargs):
        FakeBot.captured["set_my_description"] = kwargs
        return True


def test_send_text_sync_passes_business_connection_id(monkeypatch) -> None:
    FakeBot.captured = {}
    monkeypatch.setattr(telegram_service_module, "Bot", FakeBot)

    message_id = TelegramService().send_text_sync(
        "bot-token",
        "6059820900",
        "您好",
        business_connection_id="business-connection-1",
    )

    assert message_id == 12345
    assert FakeBot.captured["token"] == "bot-token"
    assert FakeBot.captured["send_message"]["chat_id"] == "6059820900"
    assert FakeBot.captured["send_message"]["text"] == "您好"
    assert FakeBot.captured["send_message"]["business_connection_id"] == "business-connection-1"
    assert FakeBot.captured["session"].closed is True


def test_send_chat_action_sync_passes_business_connection_id(monkeypatch) -> None:
    FakeBot.captured = {}
    monkeypatch.setattr(telegram_service_module, "Bot", FakeBot)

    TelegramService().send_chat_action_sync(
        "bot-token",
        "6059820900",
        business_connection_id="business-connection-1",
    )

    assert FakeBot.captured["send_chat_action"]["chat_id"] == "6059820900"
    assert FakeBot.captured["send_chat_action"]["action"] == "typing"
    assert FakeBot.captured["send_chat_action"]["business_connection_id"] == "business-connection-1"
    assert FakeBot.captured["session"].closed is True


def test_set_bot_description_sync_calls_telegram_api(monkeypatch) -> None:
    FakeBot.captured = {}
    monkeypatch.setattr(telegram_service_module, "Bot", FakeBot)

    result = TelegramService().set_bot_description_sync("bot-token", "客服 Bot 说明")

    assert result is True
    assert FakeBot.captured["token"] == "bot-token"
    assert FakeBot.captured["set_my_description"]["description"] == "客服 Bot 说明"
    assert FakeBot.captured["session"].closed is True
