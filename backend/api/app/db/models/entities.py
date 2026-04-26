from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.api.app.core.defaults import DEFAULT_BOT_WELCOME_MESSAGE, DEFAULT_EMAIL_AUTO_REPLY_MESSAGE, DEFAULT_UNANSWERED_FALLBACK_MESSAGE
from backend.api.app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConversationStatus(StrEnum):
    OPEN = "open"
    HANDOFF = "handoff"
    CLOSED = "closed"


class MessageSource(StrEnum):
    CUSTOMER = "customer"
    BOT = "bot"
    AGENT = "agent"
    SYSTEM = "system"


class MessageChannel(StrEnum):
    TELEGRAM_DM = "telegram_dm"
    TELEGRAM_GROUP = "telegram_group"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DeliveryStatus(StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    SENT = "sent"
    FAILED = "failed"


class UserRole(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    AGENT = "agent"


class HandoffStatus(StrEnum):
    OPEN = "open"
    ACTIVE = "active"
    RELEASED = "released"
    CLOSED = "closed"


class PromptTemplateType(StrEnum):
    ROUTER = "router"
    GROUNDING = "grounding"
    HUMANIZER = "humanizer"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bot_profiles: Mapped[list["BotProfile"]] = relationship(back_populates="tenant")
    users: Mapped[list["User"]] = relationship(back_populates="tenant")


class BotProfile(Base):
    __tablename__ = "bot_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    telegram_bot_token: Mapped[str] = mapped_column(String(512))
    telegram_bot_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    support_group_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    welcome_message: Mapped[str] = mapped_column(Text, default=DEFAULT_BOT_WELCOME_MESSAGE)
    unanswered_fallback_message: Mapped[str] = mapped_column(Text, default=DEFAULT_UNANSWERED_FALLBACK_MESSAGE)
    email_auto_reply_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_auto_reply_message: Mapped[str] = mapped_column(Text, default=DEFAULT_EMAIL_AUTO_REPLY_MESSAGE)
    language: Mapped[str] = mapped_column(String(32), default="zh")
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    faq_hint_keywords_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    high_risk_keywords_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    sensitive_keywords_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    working_hours_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    forbidden_topics_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tenant: Mapped["Tenant"] = relationship(back_populates="bot_profiles")
    business_connections: Mapped[list["TelegramBusinessConnection"]] = relationship(back_populates="bot_profile")


class TelegramBusinessConnection(Base):
    __tablename__ = "telegram_business_connections"
    __table_args__ = (
        UniqueConstraint("bot_profile_id", "connection_id", name="uq_telegram_business_connection_bot_connection"),
        Index("ix_telegram_business_connections_bot_updated", "bot_profile_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    bot_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bot_profiles.id"), index=True)
    connection_id: Mapped[str] = mapped_column(String(255))
    telegram_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_user_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    can_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rights_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    bot_profile: Mapped["BotProfile"] = relationship(back_populates="business_connections")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=True)
    login_username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SqlEnum(UserRole, native_enum=False, length=32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tenant: Mapped["Tenant"] = relationship(back_populates="users")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_tenant_telegram_chat", "tenant_id", "telegram_chat_id"),
        Index("ix_conversations_bot_business_chat", "bot_profile_id", "telegram_business_connection_id", "telegram_chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    bot_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bot_profiles.id"), index=True)
    telegram_user_id: Mapped[str] = mapped_column(String(255))
    telegram_chat_id: Mapped[str] = mapped_column(String(255))
    telegram_business_connection_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ConversationStatus] = mapped_column(SqlEnum(ConversationStatus, native_enum=False), default=ConversationStatus.OPEN)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_customer_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_agent_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    handoff_ticket_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created_at", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    source: Mapped[MessageSource] = mapped_column(SqlEnum(MessageSource, native_enum=False))
    channel: Mapped[MessageChannel] = mapped_column(SqlEnum(MessageChannel, native_enum=False))
    telegram_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_text: Mapped[str] = mapped_column(Text, default="")
    raw_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_level: Mapped[RiskLevel] = mapped_column(SqlEnum(RiskLevel, native_enum=False), default=RiskLevel.LOW)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(SqlEnum(DeliveryStatus, native_enum=False), default=DeliveryStatus.RECEIVED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class FAQEntry(Base):
    __tablename__ = "faq_entries"
    __table_args__ = (Index("ix_faq_bot_status_priority", "bot_profile_id", "status", "priority"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    bot_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bot_profiles.id"), index=True)
    question_patterns_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    canonical_answer: Mapped[str] = mapped_column(Text)
    image_assets_json: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    answer_style_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_scope: Mapped[str | None] = mapped_column(String(128), nullable=True)
    risk_level: Mapped[RiskLevel] = mapped_column(SqlEnum(RiskLevel, native_enum=False), default=RiskLevel.LOW)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgePage(Base):
    __tablename__ = "knowledge_pages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    bot_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bot_profiles.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body_markdown: Mapped[str] = mapped_column(Text)
    image_assets_json: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    tags_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    product_scope: Mapped[str | None] = mapped_column(String(128), nullable=True)
    risk_level: Mapped[RiskLevel] = mapped_column(SqlEnum(RiskLevel, native_enum=False), default=RiskLevel.LOW)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    knowledge_page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_pages.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content_text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HandoffTicket(Base):
    __tablename__ = "handoff_tickets"
    __table_args__ = (Index("ix_handoff_conversation_status", "conversation_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    group_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_thread_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[HandoffStatus] = mapped_column(SqlEnum(HandoffStatus, native_enum=False), default=HandoffStatus.OPEN)
    reason: Mapped[str] = mapped_column(String(255))
    summary_text: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(32), default="system")
    assigned_agent_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StyleProfile(Base):
    __tablename__ = "style_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    bot_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bot_profiles.id"), index=True)
    tone: Mapped[str] = mapped_column(String(128), default="professional")
    persona_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    banned_phrases_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    delay_min_ms: Mapped[int] = mapped_column(Integer, default=1200)
    delay_max_ms: Mapped[int] = mapped_column(Integer, default=2800)
    typing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    clarify_max_turns: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    bot_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bot_profiles.id"), index=True)
    template_type: Mapped[PromptTemplateType] = mapped_column(SqlEnum(PromptTemplateType, native_enum=False))
    template_text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(255))
    target_type: Mapped[str] = mapped_column(String(255))
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
