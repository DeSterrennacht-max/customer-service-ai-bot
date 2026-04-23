from __future__ import annotations

from datetime import timedelta

from backend.api.app.db.session import SessionLocal
from backend.api.app.services.handoff_service import HandoffService
from backend.worker.app.celery_app import celery_app


@celery_app.task(name="release_stale_handoffs")
def release_stale_handoffs() -> dict:
    db = SessionLocal()
    try:
        released = HandoffService().release_stale_conversations(db, stale_after=timedelta(hours=8))
        db.commit()
        return {
            "status": "ok",
            "released_count": len(released),
            "conversation_ids": [str(conversation.id) for conversation in released],
        }
    finally:
        db.close()
