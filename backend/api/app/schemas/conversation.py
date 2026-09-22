from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from backend.api.app.db.models.entities import ConversationStatus, DeliveryStatus, MessageChannel, MessageSource, RiskLevel
from backend.api.app.schemas.common import BaseResponse


class DeliveryResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    kind: str
    status: str
    attempts: int
    last_error: str | None = None


class RetryDeliveryRequest(BaseModel):
    confirm_uncertain: bool = False


class MessageResponse(BaseResponse):
    tenant_id: UUID
    conversation_id: UUID
    source: MessageSource
    channel: MessageChannel
    telegram_message_id: str | None = None
    reply_to_message_id: str | None = None
    content_text: str
    intent: str | None = None
    risk_level: RiskLevel
    delivery_status: DeliveryStatus
    deliveries: list[DeliveryResponse] = []


class ConversationResponse(BaseResponse):
    tenant_id: UUID
    bot_profile_id: UUID
    telegram_user_id: str
    telegram_chat_id: str
    telegram_business_connection_id: str | None = None
    customer_display_name: str | None = None
    status: ConversationStatus
    last_message_at: datetime | None = None
    last_customer_message_at: datetime | None = None
    assigned_agent_user_id: UUID | None = None
    handoff_ticket_id: UUID | None = None


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse]


class HandoffActionResponse(BaseModel):
    conversation_id: UUID
    handoff_ticket_id: UUID | None = None
    status: str
