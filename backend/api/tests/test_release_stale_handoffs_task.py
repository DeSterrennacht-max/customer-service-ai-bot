from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from backend.worker.app.tasks import release_stale_handoffs as task_module


def test_release_stale_handoffs_returns_released_ids(monkeypatch) -> None:
    released_conversations = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    events: dict[str, bool] = {"committed": False, "closed": False}

    class FakeDb:
        def commit(self) -> None:
            events["committed"] = True

        def close(self) -> None:
            events["closed"] = True

    class FakeHandoffService:
        def release_stale_conversations(self, db: object, stale_after: object) -> list[object]:
            assert db is fake_db
            return released_conversations

    fake_db = FakeDb()
    monkeypatch.setattr(task_module, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(task_module, "HandoffService", lambda: FakeHandoffService())

    result = task_module.release_stale_handoffs()

    assert result["status"] == "ok"
    assert result["released_count"] == 2
    assert result["conversation_ids"] == [str(conversation.id) for conversation in released_conversations]
    assert events["committed"] is True
    assert events["closed"] is True
