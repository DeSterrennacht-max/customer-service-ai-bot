from __future__ import annotations

from backend.api.app.services.telegram_service import TelegramService
from backend.worker.app.celery_app import celery_app


@celery_app.task(name="send_reply")
def send_reply(bot_token: str, chat_id: str, text: str) -> dict:
    message_id = TelegramService().send_text_sync(bot_token, chat_id, text)
    return {"message_id": message_id}
