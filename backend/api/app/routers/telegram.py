from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.app.core.config import get_settings
from backend.api.app.db.models.entities import Message, MessageChannel, MessageSource
from backend.api.app.db.session import get_db
from backend.api.app.schemas.telegram import TelegramWebhookPayload
from backend.api.app.services.conversation_service import ConversationService
from backend.api.app.services.handoff_service import HandoffService
from backend.api.app.services.response_service import ResponseService
from backend.api.app.services.tenant_service import is_tenant_operational

router = APIRouter(prefix="/telegram", tags=["telegram"])

settings = get_settings()
conversation_service = ConversationService()
handoff_service = HandoffService()
response_service = ResponseService()


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


async def process_telegram_webhook(
    request: Request,
    db: Session,
    x_telegram_bot_api_secret_token: str | None,
    bot_identifier: str | None = None,
) -> dict[str, Any]:
    if settings.webhook_secret and x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload = TelegramWebhookPayload.model_validate(await request.json())
    message = payload.message or payload.edited_message
    if not message:
        return {"status": "ignored"}

    chat = message.get("chat", {})
    from_user = message.get("from", {})
    text = message.get("text") or message.get("caption") or ""
    message_id = str(message.get("message_id")) if message.get("message_id") is not None else None
    reply_to_message = message.get("reply_to_message") or {}
    reply_to_message_id = str(reply_to_message.get("message_id")) if reply_to_message.get("message_id") else None

    bot_profile = resolve_webhook_bot_profile(db, bot_identifier)
    chat_type = chat.get("type")

    if chat_type in {"group", "supergroup"}:
        duplicate_group_message = db.scalar(
            select(Message).where(
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
        )
        db.commit()
        return {"status": "ok", "handled": handled, "type": "group"}

    conversation = conversation_service.get_or_create_conversation(
        db=db,
        bot_profile=bot_profile,
        telegram_chat_id=str(chat.get("id")),
        telegram_user_id=str(from_user.get("id")),
        display_name=from_user.get("full_name") or from_user.get("username"),
    )
    duplicate_customer_message = db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.channel == MessageChannel.TELEGRAM_DM,
            Message.source == MessageSource.CUSTOMER,
            Message.telegram_message_id == message_id,
        )
    )
    if duplicate_customer_message:
        return {"status": "ignored", "reason": "duplicate_customer_message"}
    pipeline_result = response_service.handle_customer_message(db, conversation, text, payload.model_dump(), message_id)
    sent_text = response_service.dispatch_reply(db, conversation, pipeline_result)
    db.commit()
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
