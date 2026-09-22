from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.api.app.db.models.entities import BotProfile, Conversation, ConversationStatus, Message, MessageChannel, MessageSource, RiskLevel, User
from backend.api.app.dependencies import is_super_admin
from backend.api.app.services.tenant_service import is_tenant_operational


class ConversationService:
    def get_default_bot_profile(self, db: Session) -> BotProfile:
        bot_profiles = db.scalars(select(BotProfile).where(BotProfile.is_active.is_(True)).order_by(BotProfile.created_at.asc())).all()
        for bot_profile in bot_profiles:
            if is_tenant_operational(bot_profile.tenant):
                return bot_profile
        raise ValueError("No active bot profile configured")

    def get_bot_profile(self, db: Session, bot_profile_id: UUID) -> BotProfile | None:
        return db.get(BotProfile, bot_profile_id)

    def get_bot_profile_by_identifier(self, db: Session, bot_identifier: str) -> BotProfile | None:
        normalized = bot_identifier.strip()
        if not normalized:
            return None

        try:
            bot_profile = db.get(BotProfile, UUID(normalized))
            if bot_profile and getattr(bot_profile, "is_active", True):
                return bot_profile
            return None
        except (ValueError, TypeError):
            pass

        username = normalized.lstrip("@")
        return db.scalar(
            select(BotProfile)
            .where(
                BotProfile.is_active.is_(True),
                or_(
                    BotProfile.telegram_bot_username == username,
                    BotProfile.telegram_bot_username == f"@{username}",
                ),
            )
            .order_by(BotProfile.created_at.asc())
            .limit(1)
        )

    def get_or_create_conversation(
        self,
        db: Session,
        bot_profile: BotProfile,
        telegram_chat_id: str,
        telegram_user_id: str,
        display_name: str | None = None,
        telegram_business_connection_id: str | None = None,
    ) -> Conversation:
        business_connection_filter = (
            Conversation.telegram_business_connection_id == telegram_business_connection_id
            if telegram_business_connection_id
            else Conversation.telegram_business_connection_id.is_(None)
        )
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.bot_profile_id == bot_profile.id,
                Conversation.telegram_chat_id == telegram_chat_id,
                business_connection_filter,
            ).with_for_update()
        )
        if conversation:
            return conversation

        conversation = Conversation(
            tenant_id=bot_profile.tenant_id,
            bot_profile_id=bot_profile.id,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_business_connection_id=telegram_business_connection_id,
            customer_display_name=display_name,
            status=ConversationStatus.OPEN,
        )
        db.add(conversation)
        db.flush()
        return conversation

    def find_conversation(
        self,
        db: Session,
        bot_profile: BotProfile,
        telegram_chat_id: str,
        telegram_business_connection_id: str | None = None,
    ) -> Conversation | None:
        business_connection_filter = (
            Conversation.telegram_business_connection_id == telegram_business_connection_id
            if telegram_business_connection_id
            else Conversation.telegram_business_connection_id.is_(None)
        )
        return db.scalar(
            select(Conversation).where(
                Conversation.bot_profile_id == bot_profile.id,
                Conversation.telegram_chat_id == telegram_chat_id,
                business_connection_filter,
            ).with_for_update()
        )

    def record_message(
        self,
        db: Session,
        conversation: Conversation,
        source: MessageSource,
        channel: MessageChannel,
        content_text: str,
        raw_payload_json: dict[str, Any] | None,
        telegram_message_id: str | None,
        reply_to_message_id: str | None = None,
        intent: str | None = None,
        risk_level: RiskLevel = RiskLevel.LOW,
    ) -> Message:
        message = Message(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            source=source,
            channel=channel,
            telegram_message_id=telegram_message_id,
            telegram_chat_id=conversation.telegram_chat_id,
            reply_to_message_id=reply_to_message_id,
            content_text=content_text,
            raw_payload_json=raw_payload_json,
            intent=intent,
            risk_level=risk_level,
        )
        db.add(message)
        conversation.last_message_at = datetime.now(timezone.utc)
        if source == MessageSource.CUSTOMER:
            conversation.last_customer_message_at = conversation.last_message_at
        db.flush()
        return message

    def list_conversations(self, db: Session, user: User) -> list[Conversation]:
        statement = select(Conversation)
        if not is_super_admin(user):
            statement = statement.where(Conversation.tenant_id == user.tenant_id)
        return list(
            db.scalars(
                statement.order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
            ).all()
        )

    def get_conversation_detail(self, db: Session, conversation_id: str, user: User) -> Conversation | None:
        statement = (
            select(Conversation)
            .options(joinedload(Conversation.messages).selectinload(Message.deliveries))
            .where(Conversation.id == UUID(conversation_id))
        )
        if not is_super_admin(user):
            statement = statement.where(Conversation.tenant_id == user.tenant_id)
        return db.execute(statement).unique().scalar_one_or_none()
