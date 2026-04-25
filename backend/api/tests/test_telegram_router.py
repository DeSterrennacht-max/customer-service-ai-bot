from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api.app.routers import telegram as telegram_router
from backend.api.app.routers.telegram import conversation_service, process_telegram_webhook, resolve_webhook_bot_profile


class FakeRequest:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def json(self) -> dict:
        return self.payload


class FakeDb:
    def __init__(self, scalar_results: list[object | None] | None = None) -> None:
        self.scalar_results = scalar_results or []
        self.commits = 0

    def scalar(self, _statement: object) -> object | None:
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    def commit(self) -> None:
        self.commits += 1


def bot_profile() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        telegram_bot_token="bot-token",
        support_group_chat_id="-100300400500",
    )


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


def test_process_business_connection_update_upserts_status(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = bot_profile()
    captured: dict = {}
    connection = SimpleNamespace(connection_id="business-connection-1", can_reply=True)
    monkeypatch.setattr(telegram_router, "resolve_webhook_bot_profile", lambda db, bot_identifier: profile)

    def fake_upsert(db, bot_profile, payload):
        captured["bot_profile"] = bot_profile
        captured["payload"] = payload
        return connection

    monkeypatch.setattr(telegram_router.business_connection_service, "upsert_business_connection", fake_upsert)
    db = FakeDb()

    result = asyncio.run(
        process_telegram_webhook(
            request=FakeRequest(
                {
                    "update_id": 1,
                    "business_connection": {
                        "id": "business-connection-1",
                        "user": {"id": 9001},
                        "user_chat_id": 9001,
                        "date": 1710000000,
                        "is_enabled": True,
                        "rights": {"can_reply": True},
                    },
                }
            ),
            db=db,
            x_telegram_bot_api_secret_token=telegram_router.settings.webhook_secret,
            bot_identifier="support_bot",
        )
    )

    assert result == {
        "status": "ok",
        "type": "business_connection",
        "connection_id": "business-connection-1",
        "can_reply": True,
    }
    assert captured["bot_profile"] is profile
    assert captured["payload"]["rights"]["can_reply"] is True
    assert db.commits == 1


def test_process_regular_message_preserves_plain_bot_path(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = bot_profile()
    conversation = SimpleNamespace(id=uuid4(), telegram_business_connection_id=None)
    captured: dict = {}
    monkeypatch.setattr(telegram_router, "resolve_webhook_bot_profile", lambda db, bot_identifier: profile)

    def fake_get_or_create_conversation(**kwargs):
        captured["conversation_kwargs"] = kwargs
        return conversation

    monkeypatch.setattr(telegram_router.conversation_service, "get_or_create_conversation", fake_get_or_create_conversation)
    monkeypatch.setattr(
        telegram_router.response_service,
        "handle_customer_message",
        lambda db, conversation, text, raw_payload, telegram_message_id: SimpleNamespace(action="template_reply"),
    )
    monkeypatch.setattr(telegram_router.response_service, "dispatch_reply", lambda db, conversation, pipeline_result: "您好")
    db = FakeDb()

    result = asyncio.run(
        process_telegram_webhook(
            request=FakeRequest(
                {
                    "update_id": 2,
                    "message": {
                        "message_id": 101,
                        "chat": {"id": 6059820900, "type": "private"},
                        "from": {"id": 6059820900, "username": "customer"},
                        "text": "价格是多少",
                    },
                }
            ),
            db=db,
            x_telegram_bot_api_secret_token=telegram_router.settings.webhook_secret,
            bot_identifier="support_bot",
        )
    )

    assert result == {"status": "ok", "action": "template_reply", "sent_text": "您好"}
    assert captured["conversation_kwargs"]["telegram_business_connection_id"] is None
    assert db.commits == 1


def test_process_business_message_reuses_business_response_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = bot_profile()
    connection = SimpleNamespace(connection_id="business-connection-1", can_reply=True, is_enabled=True, telegram_user_id="9001")
    conversation = SimpleNamespace(id=uuid4(), telegram_business_connection_id="business-connection-1")
    captured: dict = {}
    monkeypatch.setattr(telegram_router, "resolve_webhook_bot_profile", lambda db, bot_identifier: profile)
    monkeypatch.setattr(telegram_router.business_connection_service, "ensure_placeholder_connection", lambda db, bot_profile, connection_id: connection)
    monkeypatch.setattr(telegram_router.business_connection_service, "can_reply", lambda connection: True)

    def fake_find_conversation(**kwargs):
        captured["conversation_kwargs"] = kwargs
        return conversation

    def fake_handle_business_customer_message(**kwargs):
        captured["pipeline"] = {
            "conversation": kwargs["conversation"],
            "text": kwargs["text"],
            "telegram_message_id": kwargs["telegram_message_id"],
            "business_connection_id": kwargs["business_connection_id"],
        }
        return conversation, SimpleNamespace(action="template_reply")

    monkeypatch.setattr(telegram_router.conversation_service, "find_conversation", fake_find_conversation)
    monkeypatch.setattr(telegram_router.response_service, "handle_business_customer_message", fake_handle_business_customer_message)
    monkeypatch.setattr(telegram_router.response_service, "dispatch_reply", lambda db, conversation, pipeline_result: "Business reply")
    db = FakeDb()

    result = asyncio.run(
        process_telegram_webhook(
            request=FakeRequest(
                {
                    "update_id": 3,
                    "business_message": {
                        "business_connection_id": "business-connection-1",
                        "message_id": 201,
                        "chat": {"id": 6059820900, "type": "private"},
                        "from": {"id": 6059820900, "username": "customer"},
                        "text": "功能有哪些",
                    },
                }
            ),
            db=db,
            x_telegram_bot_api_secret_token=telegram_router.settings.webhook_secret,
            bot_identifier="support_bot",
        )
    )

    assert result == {"status": "ok", "action": "template_reply", "sent_text": "Business reply"}
    assert captured["conversation_kwargs"]["telegram_business_connection_id"] == "business-connection-1"
    assert captured["pipeline"]["business_connection_id"] == "business-connection-1"
    assert db.commits == 1


def test_process_business_message_ignores_miss_without_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = bot_profile()
    connection = SimpleNamespace(connection_id="business-connection-1", can_reply=True, is_enabled=True, telegram_user_id="9001")
    monkeypatch.setattr(telegram_router, "resolve_webhook_bot_profile", lambda db, bot_identifier: profile)
    monkeypatch.setattr(telegram_router.business_connection_service, "ensure_placeholder_connection", lambda db, bot_profile, connection_id: connection)
    monkeypatch.setattr(telegram_router.business_connection_service, "can_reply", lambda connection: True)
    monkeypatch.setattr(telegram_router.conversation_service, "find_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        telegram_router.response_service,
        "handle_business_customer_message",
        lambda **kwargs: (None, SimpleNamespace(action="ignored", intent="unanswered")),
    )
    monkeypatch.setattr(
        telegram_router.response_service,
        "dispatch_reply",
        lambda *args, **kwargs: pytest.fail("Ignored Business miss should not be dispatched"),
    )
    db = FakeDb()

    result = asyncio.run(
        process_telegram_webhook(
            request=FakeRequest(
                {
                    "update_id": 31,
                    "business_message": {
                        "business_connection_id": "business-connection-1",
                        "message_id": 203,
                        "chat": {"id": 6059820900, "type": "private"},
                        "from": {"id": 6059820900, "username": "customer"},
                        "text": "一个没有命中的问题",
                    },
                }
            ),
            db=db,
            x_telegram_bot_api_secret_token=telegram_router.settings.webhook_secret,
            bot_identifier="support_bot",
        )
    )

    assert result == {"status": "ignored", "action": "ignored", "reason": "unanswered"}
    assert db.commits == 1


def test_process_business_message_ignores_without_reply_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = bot_profile()
    connection = SimpleNamespace(connection_id="business-connection-1", can_reply=False, is_enabled=True, telegram_user_id="9001")
    monkeypatch.setattr(telegram_router, "resolve_webhook_bot_profile", lambda db, bot_identifier: profile)
    monkeypatch.setattr(telegram_router.business_connection_service, "ensure_placeholder_connection", lambda db, bot_profile, connection_id: connection)
    monkeypatch.setattr(telegram_router.business_connection_service, "can_reply", lambda connection: False)
    monkeypatch.setattr(
        telegram_router.conversation_service,
        "find_conversation",
        lambda **kwargs: pytest.fail("Business message without reply permission should not create or load a conversation"),
    )
    monkeypatch.setattr(
        telegram_router.conversation_service,
        "record_message",
        lambda *args, **kwargs: pytest.fail("Business message without reply permission should not be recorded"),
    )
    monkeypatch.setattr(
        telegram_router.response_service,
        "handle_business_customer_message",
        lambda *args, **kwargs: pytest.fail("Business message without reply permission should not auto-reply"),
    )
    db = FakeDb()

    result = asyncio.run(
        process_telegram_webhook(
            request=FakeRequest(
                {
                    "update_id": 4,
                    "business_message": {
                        "business_connection_id": "business-connection-1",
                        "message_id": 202,
                        "chat": {"id": 6059820900, "type": "private"},
                        "from": {"id": 6059820900, "username": "customer"},
                        "text": "价格是多少",
                    },
                }
            ),
            db=db,
            x_telegram_bot_api_secret_token=telegram_router.settings.webhook_secret,
            bot_identifier="support_bot",
        )
    )

    assert result == {"status": "ignored", "reason": "business_connection_cannot_reply"}
    assert db.commits == 1


def test_edited_business_message_duplicate_does_not_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = bot_profile()
    connection = SimpleNamespace(connection_id="business-connection-1", can_reply=True, is_enabled=True, telegram_user_id="9001")
    conversation = SimpleNamespace(id=uuid4(), telegram_business_connection_id="business-connection-1")
    monkeypatch.setattr(telegram_router, "resolve_webhook_bot_profile", lambda db, bot_identifier: profile)
    monkeypatch.setattr(telegram_router.business_connection_service, "ensure_placeholder_connection", lambda db, bot_profile, connection_id: connection)
    monkeypatch.setattr(telegram_router.business_connection_service, "can_reply", lambda connection: True)
    monkeypatch.setattr(telegram_router.conversation_service, "find_conversation", lambda **kwargs: conversation)
    monkeypatch.setattr(
        telegram_router.response_service,
        "handle_business_customer_message",
        lambda *args, **kwargs: pytest.fail("Duplicate edited business message should not auto-reply"),
    )
    db = FakeDb(scalar_results=[SimpleNamespace(id=uuid4())])

    result = asyncio.run(
        process_telegram_webhook(
            request=FakeRequest(
                {
                    "update_id": 5,
                    "edited_business_message": {
                        "business_connection_id": "business-connection-1",
                        "message_id": 202,
                        "chat": {"id": 6059820900, "type": "private"},
                        "from": {"id": 6059820900, "username": "customer"},
                        "text": "价格是多少？",
                    },
                }
            ),
            db=db,
            x_telegram_bot_api_secret_token=telegram_router.settings.webhook_secret,
            bot_identifier="support_bot",
        )
    )

    assert result == {"status": "ignored", "reason": "duplicate_customer_message"}
