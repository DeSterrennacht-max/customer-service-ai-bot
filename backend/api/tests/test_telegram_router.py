from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.app.routers.telegram import conversation_service, resolve_webhook_bot_profile


def test_resolve_webhook_bot_profile_uses_identifier_specific_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = SimpleNamespace(id="bot-1", tenant=SimpleNamespace(status="active", valid_from=None, valid_until=None))

    monkeypatch.setattr(conversation_service, "get_bot_profile_by_identifier", lambda db, bot_identifier: expected)

    resolved = resolve_webhook_bot_profile(object(), "bot-1")

    assert resolved is expected


def test_resolve_webhook_bot_profile_rejects_unknown_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation_service, "get_bot_profile_by_identifier", lambda db, bot_identifier: None)

    with pytest.raises(HTTPException) as exc_info:
        resolve_webhook_bot_profile(object(), "missing-bot")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Bot profile not found"


def test_resolve_webhook_bot_profile_falls_back_to_default_for_legacy_route(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = SimpleNamespace(id="default-bot", tenant=SimpleNamespace(status="active", valid_from=None, valid_until=None))

    monkeypatch.setattr(conversation_service, "get_default_bot_profile", lambda db: expected)

    resolved = resolve_webhook_bot_profile(object(), None)

    assert resolved is expected


def test_resolve_webhook_bot_profile_rejects_inactive_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = SimpleNamespace(
        id="bot-1",
        tenant=SimpleNamespace(status="inactive", valid_from=None, valid_until=None),
    )

    monkeypatch.setattr(conversation_service, "get_bot_profile_by_identifier", lambda db, bot_identifier: expected)

    with pytest.raises(HTTPException) as exc_info:
        resolve_webhook_bot_profile(object(), "bot-1")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Tenant is not active"


def test_resolve_webhook_bot_profile_rejects_expired_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = SimpleNamespace(
        id="bot-1",
        tenant=SimpleNamespace(status="active", valid_from=None, valid_until=datetime.now(timezone.utc) - timedelta(days=1)),
    )

    monkeypatch.setattr(conversation_service, "get_bot_profile_by_identifier", lambda db, bot_identifier: expected)

    with pytest.raises(HTTPException) as exc_info:
        resolve_webhook_bot_profile(object(), "bot-1")

    assert exc_info.value.status_code == 403
