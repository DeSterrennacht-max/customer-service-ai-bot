from __future__ import annotations

from backend.api.app.db.session import SessionLocal
from backend.api.app.services.conversation_service import ConversationService
from backend.api.app.services.response_service import ResponseService
from backend.worker.app.celery_app import celery_app


@celery_app.task(name="process_incoming_message")
def process_incoming_message(conversation_id: str, text: str, raw_payload: dict, telegram_message_id: str | None = None) -> dict:
    db = SessionLocal()
    try:
        conversation = ConversationService().get_conversation_detail(db, conversation_id)
        if not conversation:
            return {"status": "ignored", "reason": "conversation_not_found"}
        service = ResponseService()
        result = service.handle_customer_message(db, conversation, text, raw_payload, telegram_message_id)
        sent_text = service.dispatch_reply(db, conversation, result)
        db.commit()
        return {"status": "ok", "action": result.action, "sent_text": sent_text}
    finally:
        db.close()
