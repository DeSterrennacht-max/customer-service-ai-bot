"""Durable outbound messages. Telegram has no idempotency key: uncertain sends need review."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter, TelegramUnauthorizedError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.app.core.config import get_settings
from backend.api.app.db.models.entities import (
    BotProfile, Conversation, ConversationStatus, DeliveryStatus, HandoffStatus,
    HandoffTicket, Message, MessageChannel, MessageSource, OutboundDelivery, StyleProfile,
)
from backend.api.app.llm.generator_client import GeneratorLLMClient
from backend.api.app.services.tenant_service import is_tenant_operational

logger = logging.getLogger(__name__)


def queue_message(db: Session, conversation: Conversation, message: Message, chat_id: str, *,
                  text: str = "", image_assets: list | None = None, business_connection_id: str | None = None,
                  automatic: bool = False, humanize: bool = False, structured: bool = False) -> None:
    message.delivery_status = DeliveryStatus.PENDING
    db.flush()
    created_at = datetime.now(timezone.utc)
    # 2,000 Unicode code points fit within Telegram's 4,096 UTF-16-unit text limit.
    parts = [("text", {"text": text[i:i + 2000], "humanize": humanize, "structured": structured})
             for i in range(0, len(text), 2000) if text[i:i + 2000].strip()]
    parts.extend(("photo", {"url": str(asset["url"])}) for asset in (image_assets or []) if asset.get("url"))
    for sequence, (kind, payload) in enumerate(parts):
        db.add(OutboundDelivery(bot_profile_id=conversation.bot_profile_id, message_id=message.id,
            chat_id=chat_id, business_connection_id=business_connection_id, kind=kind,
            payload_json=payload, automatic=automatic, sequence=sequence, created_at=created_at,
            status="pending", attempts=0, next_attempt_at=created_at))


def update_message_status(db: Session, message: Message) -> None:
    db.flush()
    deliveries = list(db.scalars(select(OutboundDelivery).where(OutboundDelivery.message_id == message.id)
                                 .order_by(OutboundDelivery.sequence)).all())
    states = {item.status for item in deliveries}
    if "uncertain" in states:
        message.delivery_status = DeliveryStatus.UNCERTAIN
    elif states & {"pending", "queued", "preparing", "sending"}:
        message.delivery_status = DeliveryStatus.PENDING
    elif states == {"sent"}:
        message.delivery_status = DeliveryStatus.SENT
    elif "sent" in states:
        message.delivery_status = DeliveryStatus.PARTIAL
    elif states == {"cancelled"}:
        message.delivery_status = DeliveryStatus.CANCELLED
    else:
        message.delivery_status = DeliveryStatus.FAILED
    sent = [item for item in deliveries if item.telegram_message_id]
    payload = dict(message.raw_payload_json or {})
    payload["text_message_ids"] = [item.telegram_message_id for item in sent if item.kind == "text"]
    payload["photo_message_ids"] = [item.telegram_message_id for item in sent if item.kind == "photo"]
    if message.source == MessageSource.AGENT:
        payload["outbound_customer_message_id"] = sent[0].telegram_message_id if sent else None
    elif sent:
        message.telegram_message_id = sent[0].telegram_message_id
    text_parts = [item for item in deliveries if item.kind == "text"]
    if text_parts and all(item.status == "sent" for item in text_parts):
        message.content_text = "".join(item.payload_json.get("rendered_text", item.payload_json["text"]) for item in text_parts)
    message.raw_payload_json = payload


def prepare_payload(payload: dict, style: dict) -> dict:
    prepared = dict(payload)
    if "text" not in payload or "rendered_text" in payload:
        return prepared
    text = payload["text"]
    if payload.get("humanize") and style:
        generator = GeneratorLLMClient()
        try:
            if payload.get("structured"):
                text = generator.preserve_structure(text, style["banned_phrases"]).text
            else:
                text = generator.humanize(text, style["tone"], style["banned_phrases"]).text
        except Exception:
            logger.warning("Reply rewrite failed; using saved canonical response")
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-16-le")) // 2 > 4096:
            text = payload["text"]
    prepared["rendered_text"] = text
    return prepared


async def send_delivery(token: str, item: dict, style: dict) -> int:
    async with Bot(token=token, session=AiohttpSession(timeout=20)).context() as bot:
        if item["kind"] == "text":
            if style.get("typing_enabled") and item["payload"].get("humanize"):
                try:
                    await bot.send_chat_action(chat_id=item["chat_id"], action="typing", business_connection_id=item["business_connection_id"])
                except Exception:
                    logger.info("Typing indicator unavailable; continuing delivery")
                await asyncio.sleep(random.randint(style["delay_min_ms"], style["delay_max_ms"]) / 1000)
            result = await bot.send_message(chat_id=item["chat_id"], text=item["payload"]["rendered_text"], business_connection_id=item["business_connection_id"])
        else:
            result = await bot.send_photo(chat_id=item["chat_id"], photo=item["payload"]["url"], business_connection_id=item["business_connection_id"])
        return result.message_id


def snapshot_style(db: Session, bot_id: UUID) -> dict:
    style = db.scalar(select(StyleProfile).where(StyleProfile.bot_profile_id == bot_id))
    if not style:
        return {}
    minimum = max(0, min(style.delay_min_ms, 30000))
    return {"tone": style.tone, "banned_phrases": style.banned_phrases_json or [],
            "typing_enabled": style.typing_enabled, "delay_min_ms": minimum,
            "delay_max_ms": max(minimum, min(style.delay_max_ms, 30000))}


def deliver_locked(db: Session, delivery_id: UUID, *, sender=None) -> str:
    """Caller holds the conversation advisory lock across commits and network calls."""
    now = datetime.now(timezone.utc)
    item = db.get(OutboundDelivery, delivery_id)
    if not item or item.status not in {"pending", "queued"} or item.next_attempt_at > now:
        return "not_due"
    message = db.get(Message, item.message_id)
    conversation = db.get(Conversation, message.conversation_id)
    bot = db.get(BotProfile, item.bot_profile_id)
    waiting = list(db.scalars(select(OutboundDelivery).join(Message)
        .where(Message.conversation_id == conversation.id, OutboundDelivery.status.in_(["pending", "queued", "preparing", "sending"]))
        .order_by(OutboundDelivery.created_at, OutboundDelivery.sequence, OutboundDelivery.id)).all())
    if waiting and waiting[0].id != item.id:
        item.status = "pending"
        item.started_at = None
        db.commit()
        return "waiting"
    earlier = list(db.scalars(select(OutboundDelivery).where(OutboundDelivery.message_id == message.id,
                             OutboundDelivery.sequence < item.sequence)).all())
    blocked_part = any(part.status in {"failed", "uncertain", "cancelled"} for part in earlier)
    metadata = message.raw_payload_json or {}
    if metadata.get("handoff_group_message_type") and metadata.get("handoff_ticket_id"):
        ticket = db.get(HandoffTicket, UUID(metadata["handoff_ticket_id"]))
        blocked_part = blocked_part or not ticket or ticket.status not in {HandoffStatus.OPEN, HandoffStatus.ACTIVE}
    if (blocked_part or not bot or not bot.is_active or not is_tenant_operational(bot.tenant)
            or (item.automatic and conversation.status == ConversationStatus.HANDOFF)):
        item.status = "cancelled"
        item.last_error = "Delivery cancelled because conversation, bot, or preceding part is unavailable"
        update_message_status(db, message)
        db.commit()
        return item.status
    item.attempts += 1
    item.status = "preparing"
    item.started_at = now
    style = snapshot_style(db, bot.id)
    token = bot.telegram_bot_token
    payload = dict(item.payload_json)
    db.commit()
    # No open database transaction while calling the language model.
    try:
        prepared = prepare_payload(payload, style)
    except Exception as exc:
        item.status = "failed" if item.attempts >= get_settings().delivery_max_attempts else "pending"
        item.next_attempt_at = now + timedelta(seconds=min(300, 2 ** item.attempts))
        item.last_error = type(exc).__name__
        update_message_status(db, message)
        db.commit()
        return item.status
    db.refresh(conversation)
    db.refresh(bot)
    if (item.automatic and conversation.status == ConversationStatus.HANDOFF) or not bot.is_active or not is_tenant_operational(bot.tenant):
        item.status = "cancelled"
        update_message_status(db, message)
        db.commit()
        return item.status
    item.payload_json = prepared
    item.status = "sending"
    item.started_at = datetime.now(timezone.utc)
    request = {"kind": item.kind, "chat_id": item.chat_id, "business_connection_id": item.business_connection_id, "payload": prepared}
    db.commit()
    try:
        telegram_id = sender(token, request, style) if sender else asyncio.run(send_delivery(token, request, style))
        if not telegram_id:
            raise RuntimeError("Missing Telegram acknowledgement")
        item.telegram_message_id = str(telegram_id)
        item.status = "sent"
        item.last_error = None
    except TelegramRetryAfter as exc:
        item.status = "failed" if item.attempts >= get_settings().delivery_max_attempts else "pending"
        item.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, exc.retry_after))
        item.last_error = "TelegramRetryAfter"
    except (TelegramBadRequest, TelegramForbiddenError, TelegramUnauthorizedError) as exc:
        item.status = "failed"
        item.last_error = type(exc).__name__
    except Exception as exc:
        # Timeout, connection loss or worker death can happen after Telegram accepted the send.
        item.status = "uncertain"
        item.last_error = type(exc).__name__
    update_message_status(db, message)
    metadata = message.raw_payload_json or {}
    if item.status == "sent" and metadata.get("handoff_group_message_type") == "summary" and item.sequence == 0:
        ticket = db.get(HandoffTicket, UUID(metadata["handoff_ticket_id"]))
        if ticket and ticket.status == HandoffStatus.OPEN:
            ticket.group_thread_key = item.telegram_message_id
            ticket.status = HandoffStatus.ACTIVE
    db.commit()
    return item.status


def recover_interrupted_deliveries(db: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    rows = db.scalars(select(OutboundDelivery).where(OutboundDelivery.status.in_(["preparing", "sending"]),
                      OutboundDelivery.started_at < cutoff).with_for_update(skip_locked=True)).all()
    for item in rows:
        item.status = "pending" if item.status == "preparing" else "uncertain"
        item.last_error = "Worker interrupted; delivery outcome requires review" if item.status == "uncertain" else "Preparation interrupted"
        update_message_status(db, db.get(Message, item.message_id))
    db.commit()
    return len(rows)
