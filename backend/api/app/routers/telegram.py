from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from starlette.concurrency import run_in_threadpool
from pydantic import ValidationError
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.api.app.core.config import get_settings
from backend.api.app.db.models.entities import Conversation, Message, MessageChannel, MessageSource, TelegramUpdate
from backend.api.app.db.session import get_db
from backend.api.app.schemas.telegram import TelegramWebhookPayload
from backend.api.app.services.conversation_service import ConversationService
from backend.api.app.services.handoff_service import HandoffService
from backend.api.app.services.response_service import ResponseService
from backend.api.app.services.telegram_business_service import TelegramBusinessConnectionService
from backend.api.app.services.tenant_service import is_tenant_operational

router = APIRouter(prefix="/telegram", tags=["telegram"])

settings = get_settings()
conversation_service = ConversationService()
handoff_service = HandoffService()
response_service = ResponseService()
business_connection_service = TelegramBusinessConnectionService()


def resolve_webhook_bot_profile(db: Session, bot_identifier: str | None) -> object:
    try:
        if bot_identifier:
            bot_profile = conversation_service.get_bot_profile_by_identifier(db, bot_identifier)
            if not bot_profile:
                raise HTTPException(status_code=404, detail="Bot profile not found")
        else:
            bot_profile = conversation_service.get_default_bot_profile(db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="No active bot profile configured") from exc

    if not is_tenant_operational(bot_profile.tenant):
        raise HTTPException(status_code=403, detail="Tenant is not active")
    return bot_profile


def display_name_from_user(from_user: dict[str, Any]) -> str | None:
    full_name = str(from_user.get("full_name") or "").strip()
    if full_name:
        return full_name
    name_parts = [str(from_user.get("first_name") or "").strip(), str(from_user.get("last_name") or "").strip()]
    joined_name = " ".join(part for part in name_parts if part)
    return joined_name or from_user.get("username")


def is_duplicate_customer_message(db: Session, conversation: object, message_id: str | None) -> bool:
    if not message_id:
        return False
    duplicate_customer_message = db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.channel == MessageChannel.TELEGRAM_DM,
            Message.source == MessageSource.CUSTOMER,
            Message.telegram_message_id == message_id,
        )
    )
    return bool(duplicate_customer_message)


async def process_telegram_webhook(
    request: Request,
    db: Session,
    x_telegram_bot_api_secret_token: str | None,
    bot_identifier: str | None = None,
) -> dict[str, Any]:
    if settings.webhook_secret and x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        payload = TelegramWebhookPayload.model_validate(await request.json())
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Telegram update") from exc
    if payload.update_id is None:
        raise HTTPException(status_code=400, detail="Telegram update_id is required")
    return await run_in_threadpool(accept_update, db, payload, bot_identifier)


def accept_update(db: Session, payload: TelegramWebhookPayload, bot_identifier: str | None) -> dict[str, Any]:
    bot_profile = resolve_webhook_bot_profile(db, bot_identifier)
    now = datetime.now(timezone.utc)
    statement = insert(TelegramUpdate).values(id=uuid.uuid4(), bot_profile_id=bot_profile.id,
        update_id=payload.update_id, payload_json=payload.model_dump(), status="pending", attempts=0,
        created_at=now, next_attempt_at=now).on_conflict_do_nothing(
            constraint="uq_telegram_update_bot_update").returning(TelegramUpdate.id)
    accepted = db.scalar(statement)
    db.commit()
    return {"status": "accepted" if accepted else "ignored", "reason": "queued" if accepted else "duplicate_update"}


def process_received_update(db: Session, payload: TelegramWebhookPayload, bot_profile: object) -> dict[str, Any]:
    if payload.business_connection:
        connection = business_connection_service.upsert_business_connection(db, bot_profile, payload.business_connection)
        return {
            "status": "ok",
            "type": "business_connection",
            "connection_id": connection.connection_id if connection else None,
            "can_reply": connection.can_reply if connection else False,
        }

    if payload.deleted_business_messages:
        return {"status": "ignored", "type": "deleted_business_messages"}

    message = payload.business_message or payload.edited_business_message or payload.message or payload.edited_message
    if not message:
        return {"status": "ignored"}

    is_business_message = bool(payload.business_message or payload.edited_business_message)
    business_connection_id = str(message.get("business_connection_id") or "").strip() if is_business_message else None
    business_connection = None
    if is_business_message:
        if not business_connection_id:
            return {"status": "ignored", "reason": "missing_business_connection_id"}
        business_connection = business_connection_service.ensure_placeholder_connection(db, bot_profile, business_connection_id)

    chat = message.get("chat", {})
    from_user = message.get("from", {})
    text = message.get("text") or message.get("caption") or ""
    message_id = str(message.get("message_id")) if message.get("message_id") is not None else None
    reply_to_message = message.get("reply_to_message") or {}
    reply_to_message_id = str(reply_to_message.get("message_id")) if reply_to_message.get("message_id") else None

    chat_type = chat.get("type")

    business_user_id = str(business_connection.telegram_user_id) if business_connection and business_connection.telegram_user_id else ""
    if is_business_message and business_user_id and str(from_user.get("id") or "") == business_user_id:
        return {"status": "ignored", "reason": "business_account_outbound"}

    if is_business_message and chat_type not in {"private", None}:
        return {"status": "ignored", "reason": "business_message_not_private"}

    if chat_type in {"group", "supergroup"}:
        duplicate_group_message = db.scalar(
            select(Message).join(Conversation).where(
                Conversation.bot_profile_id == bot_profile.id,
                Message.telegram_chat_id == str(chat.get("id")),
                Message.channel == MessageChannel.TELEGRAM_GROUP,
                Message.source == MessageSource.AGENT,
                Message.telegram_message_id == message_id,
            )
        )
        if duplicate_group_message:
            return {"status": "ignored", "reason": "duplicate_group_message"}
        handled = handoff_service.handle_group_reply(
            db=db,
            group_chat_id=str(chat.get("id")),
            incoming_group_message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            text=text,
            bot_token=bot_profile.telegram_bot_token,
            bot_profile_id=bot_profile.id,
        )
        return {"status": "ok", "handled": handled, "type": "group"}

    if is_business_message:
        if not business_connection_service.can_reply(business_connection):
            return {"status": "ignored", "reason": "business_connection_cannot_reply"}

        conversation = conversation_service.find_conversation(
            db=db,
            bot_profile=bot_profile,
            telegram_chat_id=str(chat.get("id")),
            telegram_business_connection_id=business_connection_id,
        )
        if conversation and is_duplicate_customer_message(db, conversation, message_id):
            return {"status": "ignored", "reason": "duplicate_customer_message"}

        conversation, pipeline_result = response_service.handle_business_customer_message(
            db=db,
            bot_profile=bot_profile,
            conversation=conversation,
            telegram_chat_id=str(chat.get("id")),
            telegram_user_id=str(from_user.get("id")),
            display_name=display_name_from_user(from_user),
            business_connection_id=business_connection_id or "",
            text=text,
            raw_payload=payload.model_dump(),
            telegram_message_id=message_id,
        )
        if not conversation:
            return {"status": "ignored", "action": pipeline_result.action, "reason": pipeline_result.intent}

        sent_text = response_service.dispatch_reply(db, conversation, pipeline_result)
        return {"status": "ok", "action": pipeline_result.action, "sent_text": sent_text}

    conversation = conversation_service.get_or_create_conversation(
        db=db,
        bot_profile=bot_profile,
        telegram_chat_id=str(chat.get("id")),
        telegram_user_id=str(from_user.get("id")),
        display_name=display_name_from_user(from_user),
        telegram_business_connection_id=business_connection_id,
    )
    if is_duplicate_customer_message(db, conversation, message_id):
        return {"status": "ignored", "reason": "duplicate_customer_message"}

    pipeline_result = response_service.handle_customer_message(db, conversation, text, payload.model_dump(), message_id)
    sent_text = response_service.dispatch_reply(db, conversation, pipeline_result)
    return {"status": "ok", "action": pipeline_result.action, "sent_text": sent_text}


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    return await process_telegram_webhook(
        request=request,
        db=db,
        x_telegram_bot_api_secret_token=x_telegram_bot_api_secret_token,
        bot_identifier=None,
    )


@router.post("/webhook/{bot_identifier}")
async def telegram_webhook_for_bot(
    bot_identifier: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    return await process_telegram_webhook(
        request=request,
        db=db,
        x_telegram_bot_api_secret_token=x_telegram_bot_api_secret_token,
        bot_identifier=bot_identifier,
    )
