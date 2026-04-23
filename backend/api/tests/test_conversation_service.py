from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from backend.api.app.services.conversation_service import ConversationService


class FakeSession:
    def __init__(self, get_result: object | None = None, scalar_result: object | None = None) -> None:
        self.get_result = get_result
        self.scalar_result = scalar_result
        self.get_calls: list[tuple[object, object]] = []
        self.scalar_calls = 0

    def get(self, model: object, key: object) -> object | None:
        self.get_calls.append((model, key))
        return self.get_result

    def scalar(self, _statement: object) -> object | None:
        self.scalar_calls += 1
        return self.scalar_result


def test_get_bot_profile_by_identifier_prefers_uuid_lookup() -> None:
    service = ConversationService()
    bot_id = uuid4()
    bot_profile = SimpleNamespace(id=bot_id)
    db = FakeSession(get_result=bot_profile)

    resolved = service.get_bot_profile_by_identifier(db, str(bot_id))

    assert resolved is bot_profile
    assert len(db.get_calls) == 1
    assert db.scalar_calls == 0


def test_get_bot_profile_by_identifier_supports_username_lookup() -> None:
    service = ConversationService()
    bot_profile = SimpleNamespace(telegram_bot_username="support_bot")
    db = FakeSession(scalar_result=bot_profile)

    resolved = service.get_bot_profile_by_identifier(db, "@support_bot")

    assert resolved is bot_profile
    assert db.get_calls == []
    assert db.scalar_calls == 1
