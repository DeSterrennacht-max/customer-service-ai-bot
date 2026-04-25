from __future__ import annotations

from types import SimpleNamespace

from backend.api.app.services.telegram_business_service import TelegramBusinessConnectionService


def test_connection_status_distinguishes_permission_states() -> None:
    service = TelegramBusinessConnectionService()

    assert service.connection_status(None) == "not_connected"
    assert service.connection_status(SimpleNamespace(is_enabled=False, can_reply=True)) == "not_connected"
    assert service.connection_status(SimpleNamespace(is_enabled=True, can_reply=False)) == "connected_no_reply"
    assert service.connection_status(SimpleNamespace(is_enabled=True, can_reply=True)) == "ready"


def test_extract_can_reply_prefers_business_rights() -> None:
    service = TelegramBusinessConnectionService()

    assert service._extract_can_reply({"can_reply": True, "rights": {"can_reply": False}}) is False
    assert service._extract_can_reply({"rights": {"can_reply": True}}) is True
    assert service._extract_can_reply({"can_reply": True}) is True
