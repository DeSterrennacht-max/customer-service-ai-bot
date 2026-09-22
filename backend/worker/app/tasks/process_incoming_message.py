"""Consume only durably accepted updates; no administrator identity is required."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text

from backend.api.app.db.models.entities import BotProfile, TelegramUpdate
from backend.api.app.db.session import SessionLocal
from backend.api.app.routers.telegram import process_received_update
from backend.api.app.schemas.telegram import TelegramWebhookPayload
from backend.api.app.services.tenant_service import is_tenant_operational
from backend.worker.app.celery_app import celery_app


def process_update(db, update_id: UUID) -> str:
    record = db.get(TelegramUpdate, update_id)
    if not record or record.status != "pending" or record.next_attempt_at > datetime.now(timezone.utc):
        return "not_due"
    locked = db.scalar(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                       {"key": f"telegram-inbox:{record.bot_profile_id}"})
    if not locked:
        db.rollback()
        return "busy"
    db.refresh(record, with_for_update=True)
    if record.status != "pending":
        db.rollback()
        return "processed"
    first = db.scalar(select(TelegramUpdate.id).where(TelegramUpdate.bot_profile_id == record.bot_profile_id,
                      TelegramUpdate.status == "pending").order_by(TelegramUpdate.created_at, TelegramUpdate.update_id).limit(1))
    if first != record.id:
        db.rollback()
        return "waiting"
    bot = db.get(BotProfile, record.bot_profile_id)
    if not bot or not bot.is_active or not is_tenant_operational(bot.tenant):
        record.status = "ignored"
    else:
        process_received_update(db, TelegramWebhookPayload.model_validate(record.payload_json), bot)
        record.status = "processed"
    record.attempts += 1
    record.processed_at = datetime.now(timezone.utc)
    record.last_error = None
    db.commit()
    return record.status


@celery_app.task(name="process_incoming_message")
def process_incoming_message(update_id: str) -> str:
    with SessionLocal() as db:
        try:
            return process_update(db, UUID(update_id))
        except Exception as exc:
            db.rollback()
            record = db.get(TelegramUpdate, UUID(update_id), with_for_update=True)
            if record and record.status == "pending":
                record.attempts += 1
                record.status = "failed" if record.attempts >= 5 else "pending"
                record.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(300, 2 ** record.attempts))
                record.last_error = type(exc).__name__
                db.commit()
            return "failed"


@celery_app.task(name="process_pending_updates", expires=10)
def process_pending_updates() -> int:
    with SessionLocal() as db:
        ids = list(db.scalars(select(TelegramUpdate.id).where(TelegramUpdate.status == "pending",
            TelegramUpdate.next_attempt_at <= datetime.now(timezone.utc)).order_by(TelegramUpdate.created_at, TelegramUpdate.update_id).limit(100)).all())
    for update_id in ids:
        process_incoming_message(str(update_id))
    return len(ids)
