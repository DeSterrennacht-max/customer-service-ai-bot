from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.api.app.db.models.entities import Message, OutboundDelivery
from backend.api.app.db.session import SessionLocal, engine
from backend.api.app.services.delivery_service import deliver_locked, recover_interrupted_deliveries
from backend.worker.app.celery_app import celery_app


@celery_app.task(name="deliver_message", acks_late=True, reject_on_worker_lost=True, soft_time_limit=110, time_limit=120)
def deliver_message(delivery_id: str) -> str:
    with engine.connect() as connection:
        with Session(bind=connection, expire_on_commit=False) as db:
            conversation_id = db.scalar(select(Message.conversation_id).join(OutboundDelivery)
                                       .where(OutboundDelivery.id == UUID(delivery_id)))
            db.commit()
            if not conversation_id:
                return "missing"
            key = f"telegram-delivery:{conversation_id}"
            locked = connection.scalar(text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": key})
            connection.commit()
            if not locked:
                return "busy"
            try:
                return deliver_locked(db, UUID(delivery_id))
            finally:
                db.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key})
                connection.commit()


@celery_app.task(name="schedule_deliveries", expires=10)
def schedule_deliveries() -> int:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        # Leases recover a publisher crash between DB commit and broker acknowledgement.
        expired = db.scalars(select(OutboundDelivery).where(OutboundDelivery.status == "queued",
                    OutboundDelivery.started_at < now - timedelta(minutes=1)).with_for_update(skip_locked=True)).all()
        for item in expired:
            item.status = "pending"
        db.flush()
        rows = db.scalars(select(OutboundDelivery).where(OutboundDelivery.status == "pending",
                    OutboundDelivery.next_attempt_at <= now).order_by(OutboundDelivery.created_at, OutboundDelivery.sequence)
                    .limit(50).with_for_update(skip_locked=True)).all()
        ids = [str(item.id) for item in rows]
        for item in rows:
            item.status = "queued"
            item.started_at = now
        db.commit()
    for delivery_id in ids:
        deliver_message.delay(delivery_id)
    return len(ids)


@celery_app.task(name="recover_deliveries")
def recover_deliveries() -> int:
    with SessionLocal() as db:
        return recover_interrupted_deliveries(db)
