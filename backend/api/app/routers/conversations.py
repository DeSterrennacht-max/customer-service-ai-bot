from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.app.db.models.entities import Conversation
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
    conversation = db.get(Conversation, UUID(conversation_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    ensure_tenant_access(user, conversation.tenant_id)
    ticket = handoff_service.create_ticket(db, conversation, reason="manual_takeover", summary_text="Manual takeover from admin")
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
    conversation = db.get(Conversation, UUID(conversation_id))
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
