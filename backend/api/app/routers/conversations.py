from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime, timezone

from backend.api.app.db.models.entities import BotProfile, Conversation, Message, OutboundDelivery
from backend.api.app.schemas.conversation import RetryDeliveryRequest
from backend.api.app.services.delivery_service import update_message_status
from backend.api.app.db.session import get_db
from backend.api.app.dependencies import ensure_tenant_access, get_current_user
from backend.api.app.schemas.conversation import ConversationDetailResponse, ConversationResponse, HandoffActionResponse
from backend.api.app.services.audit_service import AuditService
from backend.api.app.services.conversation_service import ConversationService
from backend.api.app.services.handoff_service import HandoffService

router = APIRouter(prefix="/admin/conversations", tags=["conversations"])

conversation_service = ConversationService()
handoff_service = HandoffService()
audit_service = AuditService()


@router.post("/{conversation_id}/messages/{message_id}/retry")
def retry_delivery(conversation_id: UUID, message_id: UUID, payload: RetryDeliveryRequest,
                   db: Annotated[Session, Depends(get_db)], user: Annotated[object, Depends(get_current_user)]) -> dict:
    conversation = db.get(Conversation, conversation_id, with_for_update=True)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    ensure_tenant_access(user, conversation.tenant_id)
    message = db.get(Message, message_id)
    if not message or message.conversation_id != conversation.id:
        raise HTTPException(status_code=404, detail="Message not found")
    items = list(db.scalars(select(OutboundDelivery).where(OutboundDelivery.message_id == message_id)
                           .with_for_update()).all())
    if any(item.status in {"preparing", "sending", "queued"} for item in items):
        raise HTTPException(status_code=409, detail="消息仍在发送，请稍后重试")
    if any(item.status == "uncertain" for item in items) and not payload.confirm_uncertain:
        raise HTTPException(status_code=409, detail="请先核实是否已送达；再次发送可能产生重复消息")
    retryable = [item for item in items if item.status in {"failed", "uncertain", "cancelled"}]
    if not retryable:
        raise HTTPException(status_code=409, detail="没有可重试的发送记录")
    for item in retryable:
        item.status = "pending"
        item.attempts = 0
        item.next_attempt_at = datetime.now(timezone.utc)
        item.last_error = None
    update_message_status(db, message)
    audit_service.record(db=db, tenant_id=str(conversation.tenant_id), actor_type="user", actor_id=str(user.id),
                         action="message.retry_requested", target_type="message", target_id=str(message.id),
                         detail_json={"confirm_uncertain": payload.confirm_uncertain, "parts": len(retryable)})
    db.commit()
    return {"status": "queued", "parts": len(retryable)}


@router.get("", response_model=list[ConversationResponse])
def list_conversations(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> list[Conversation]:
    return conversation_service.list_conversations(db, user)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> Conversation:
    conversation = conversation_service.get_conversation_detail(db, conversation_id, user)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.post("/{conversation_id}/takeover", response_model=HandoffActionResponse)
def takeover_conversation(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> HandoffActionResponse:
    conversation = db.get(Conversation, UUID(conversation_id), with_for_update=True)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    ensure_tenant_access(user, conversation.tenant_id)
    ticket = handoff_service.create_ticket(db, conversation, reason="manual_takeover", summary_text="Manual takeover from admin")
    bot = db.get(BotProfile, conversation.bot_profile_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot profile not found")
    handoff_service.notify_support_group(db, ticket, conversation, bot.telegram_bot_token, bot.support_group_chat_id)
    audit_service.record(
        db=db,
        tenant_id=str(conversation.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="conversation.takeover",
        target_type="conversation",
        target_id=str(conversation.id),
        detail_json={"handoff_ticket_id": str(ticket.id)},
    )
    db.commit()
    return HandoffActionResponse(conversation_id=conversation.id, handoff_ticket_id=ticket.id, status=conversation.status.value)


@router.post("/{conversation_id}/release", response_model=HandoffActionResponse)
def release_conversation(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> HandoffActionResponse:
    conversation = db.get(Conversation, UUID(conversation_id), with_for_update=True)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    ensure_tenant_access(user, conversation.tenant_id)
    handoff_service.release(db, conversation)
    audit_service.record(
        db=db,
        tenant_id=str(conversation.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="conversation.release",
        target_type="conversation",
        target_id=str(conversation.id),
        detail_json={"handoff_ticket_id": str(conversation.handoff_ticket_id) if conversation.handoff_ticket_id else None},
    )
    db.commit()
    return HandoffActionResponse(conversation_id=conversation.id, handoff_ticket_id=conversation.handoff_ticket_id, status=conversation.status.value)
