from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from backend.api.app.db.models.entities import ConversationStatus, HandoffStatus, MessageSource
from backend.api.app.services.handoff_service import HandoffService


class FakeSession:
    def __init__(self, latest_message: object | None = None) -> None:
        self.latest_message = latest_message

    def scalar(self, _statement: object) -> object | None:
        return self.latest_message


class FakeScalarResult:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def all(self) -> list[object]:
        return list(self.items)


class HandoffDbSession:
    def __init__(
        self,
        *,
        group_messages: list[object] | None = None,
        handoff_conversations: list[object] | None = None,
        objects: dict[object, object] | None = None,
    ) -> None:
        self.group_messages = group_messages or []
        self.handoff_conversations = handoff_conversations or []
        self.objects = objects or {}
        self.added: list[object] = []

    def scalars(self, statement: object) -> FakeScalarResult:
        text = str(statement)
        if "FROM messages" in text:
            return FakeScalarResult(self.group_messages)
        return FakeScalarResult(self.handoff_conversations)

    def get(self, _model: object, key: object) -> object | None:
        return self.objects.get(key)

    def add(self, obj: object) -> None:
        self.added.append(obj)


def test_build_handoff_summary_uses_username_and_human_reason_label() -> None:
    service = HandoffService()
    db = FakeSession(
        latest_message=SimpleNamespace(
            raw_payload_json={
                "message": {
                    "from": {
                        "username": "DoctorHuii",
                    }
                }
            }
        )
    )
    conversation = SimpleNamespace(
        id=uuid4(),
        customer_display_name="DoctorHuii",
        telegram_user_id="6059820900",
    )
    ticket = SimpleNamespace(
        reason="human_request",
        summary_text="人工客服",
    )

    summary = service._build_handoff_summary(db, ticket, conversation)

    assert "客户: @DoctorHuii" in summary
    assert "原因: 客户触发人工客服介入" in summary
    assert "信息内容:\n人工客服" in summary
    assert "摘要:" not in summary


def test_customer_label_falls_back_to_display_name_when_username_missing() -> None:
    service = HandoffService()
    db = FakeSession(latest_message=SimpleNamespace(raw_payload_json={"message": {"from": {}}}))
    conversation = SimpleNamespace(
        id=uuid4(),
        customer_display_name="张三",
        telegram_user_id="6059820900",
    )

    assert service._customer_label(db, conversation) == "张三"


def test_reason_label_includes_unanswered_handoff_reason() -> None:
    assert HandoffService()._reason_label("unanswered") == "知识库未命中，需人工介入"


def test_handle_group_reply_accepts_customer_sync_message_reference() -> None:
    service = HandoffService()
    ticket_id = uuid4()
    conversation_id = uuid4()
    conversation = SimpleNamespace(
        id=conversation_id,
        tenant_id=uuid4(),
        telegram_chat_id="6059820900",
        last_message_at=None,
    )
    ticket = SimpleNamespace(
        id=ticket_id,
        conversation_id=conversation_id,
        group_chat_id="-100300400500",
        status=HandoffStatus.ACTIVE,
    )
    db = HandoffDbSession(
        group_messages=[
            SimpleNamespace(
                raw_payload_json={
                    "handoff_ticket_id": str(ticket_id),
                    "handoff_group_message_type": "customer_sync",
                }
            )
        ],
        objects={
            ticket_id: ticket,
            conversation_id: conversation,
        },
    )

    service.telegram.send_text_sync = lambda bot_token, chat_id, text: 90001
    service.audit.record = lambda **kwargs: None

    handled = service.handle_group_reply(
        db=db,
        group_chat_id="-100300400500",
        incoming_group_message_id="3002",
        reply_to_message_id="2001",
        text="您好，我来接手处理。",
        bot_token="bot-token",
    )

    assert handled is True
    assert conversation.last_message_at is not None
    assert len(db.added) == 1
    agent_message = db.added[0]
    assert agent_message.source == MessageSource.AGENT
    assert agent_message.reply_to_message_id == "2001"
    assert agent_message.telegram_message_id == "3002"


def test_handle_group_reply_forwards_with_business_connection_id() -> None:
    service = HandoffService()
    ticket_id = uuid4()
    conversation_id = uuid4()
    captured: dict = {}
    conversation = SimpleNamespace(
        id=conversation_id,
        tenant_id=uuid4(),
        telegram_chat_id="6059820900",
        telegram_business_connection_id="business-connection-1",
        last_message_at=None,
    )
    ticket = SimpleNamespace(
        id=ticket_id,
        conversation_id=conversation_id,
        group_chat_id="-100300400500",
        status=HandoffStatus.ACTIVE,
    )
    db = HandoffDbSession(
        group_messages=[
            SimpleNamespace(
                raw_payload_json={
                    "handoff_ticket_id": str(ticket_id),
                    "handoff_group_message_type": "summary",
                }
            )
        ],
        objects={
            ticket_id: ticket,
            conversation_id: conversation,
        },
    )

    def fake_send_text_sync(bot_token: str, chat_id: str, text: str, **kwargs):
        captured.update({"bot_token": bot_token, "chat_id": chat_id, "text": text, **kwargs})
        return 90002

    service.telegram.send_text_sync = fake_send_text_sync
    service.audit.record = lambda **kwargs: None

    handled = service.handle_group_reply(
        db=db,
        group_chat_id="-100300400500",
        incoming_group_message_id="3003",
        reply_to_message_id="2002",
        text="您好，我来接手处理。",
        bot_token="bot-token",
    )

    assert handled is True
    assert captured["business_connection_id"] == "business-connection-1"
    assert db.added[0].raw_payload_json["business_connection_id"] == "business-connection-1"


def test_release_stale_conversations_releases_only_expired_handoffs() -> None:
    service = HandoffService()
    now = datetime.now(timezone.utc)
    stale_ticket_id = uuid4()
    fresh_ticket_id = uuid4()
    stale_conversation = SimpleNamespace(
        id=uuid4(),
        status=ConversationStatus.HANDOFF,
        handoff_ticket_id=stale_ticket_id,
        last_customer_message_at=now - timedelta(hours=8, minutes=1),
        tenant_id=uuid4(),
    )
    fresh_conversation = SimpleNamespace(
        id=uuid4(),
        status=ConversationStatus.HANDOFF,
        handoff_ticket_id=fresh_ticket_id,
        last_customer_message_at=now - timedelta(hours=7, minutes=59),
        tenant_id=uuid4(),
    )
    stale_ticket = SimpleNamespace(id=stale_ticket_id, status=HandoffStatus.ACTIVE, released_at=None)
    fresh_ticket = SimpleNamespace(id=fresh_ticket_id, status=HandoffStatus.ACTIVE, released_at=None)
    db = HandoffDbSession(
        handoff_conversations=[stale_conversation, fresh_conversation],
        objects={
            stale_ticket_id: stale_ticket,
            fresh_ticket_id: fresh_ticket,
        },
    )

    service.audit.record = lambda **kwargs: None

    released = service.release_stale_conversations(db, stale_after=timedelta(hours=8), now=now)

    assert released == [stale_conversation]
    assert stale_conversation.status == ConversationStatus.OPEN
    assert stale_ticket.status == HandoffStatus.RELEASED
    assert stale_ticket.released_at is not None
    assert fresh_conversation.status == ConversationStatus.HANDOFF
    assert fresh_ticket.status == HandoffStatus.ACTIVE
