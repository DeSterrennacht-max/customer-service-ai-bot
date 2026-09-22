from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.api.app.core.defaults import DEFAULT_BOT_WELCOME_MESSAGE, DEFAULT_EMAIL_AUTO_REPLY_MESSAGE, DEFAULT_UNANSWERED_FALLBACK_MESSAGE
from backend.api.app.db.models.entities import (
    BotProfile,
    Conversation,
    FAQEntry,
    HandoffTicket,
    KnowledgeChunk,
    KnowledgePage,
    Message,
    PromptTemplate,
    StyleProfile,
    TelegramBusinessConnection,
    Tenant,
)
from backend.api.app.db.session import get_db
from backend.api.app.dependencies import ensure_tenant_access, get_current_user, is_super_admin
from backend.api.app.schemas.content import BotProfileCreate, BotProfileResponse, BotProfileUpdate, TelegramBotDescriptionResponse
from backend.api.app.services.audit_service import AuditService
from backend.api.app.services.telegram_business_service import TelegramBusinessConnectionService
from backend.api.app.services.telegram_service import TelegramService
from backend.api.app.services.telegram_webhook_service import TelegramWebhookRegistrationError, TelegramWebhookService

router = APIRouter(prefix="/admin/bot-profiles", tags=["bot-profiles"])
audit_service = AuditService()
telegram_webhook_service = TelegramWebhookService()
business_connection_service = TelegramBusinessConnectionService()
telegram_service = TelegramService()

DEFAULT_FAQ_HINT_KEYWORDS = ["价格", "套餐", "试用", "功能", "支持"]
DEFAULT_HIGH_RISK_KEYWORDS = ["人工", "投诉", "退款", "退费", "律师", "举报"]
DEFAULT_SENSITIVE_KEYWORDS = ["骂", "骗", "垃圾", "诈骗"]


def attach_tenant_name(bot_profile: BotProfile, tenant_name: str | None, db: Session | None = None) -> BotProfile:
    setattr(bot_profile, "tenant_name", tenant_name)
    connection = business_connection_service.latest_for_bot(db, bot_profile.id) if db else None
    setattr(bot_profile, "business_connection_status", business_connection_service.connection_status(connection))
    setattr(bot_profile, "business_connection_id", connection.connection_id if connection else None)
    setattr(bot_profile, "business_connection_updated_at", connection.updated_at if connection else None)
    return bot_profile


def register_telegram_webhook(bot_profile: BotProfile) -> str | None:
    try:
        registration = telegram_webhook_service.register_bot_profile_webhook(bot_profile)
    except TelegramWebhookRegistrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return registration.url if registration else None


def unregister_telegram_webhook(bot_profile: BotProfile) -> str | None:
    try:
        return telegram_webhook_service.unregister_bot_profile_webhook(bot_profile)
    except TelegramWebhookRegistrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def normalize_unanswered_fallback_message(value: str | None) -> str:
    normalized = (value or "").strip()
    return normalized or DEFAULT_UNANSWERED_FALLBACK_MESSAGE


def normalize_email_auto_reply_message(value: str | None) -> str:
    normalized = (value or "").strip()
    return normalized or DEFAULT_EMAIL_AUTO_REPLY_MESSAGE


def sync_telegram_bot_description(bot_profile: BotProfile, description: str | None) -> bool:
    normalized = (description or "").strip()
    if not normalized:
        return False
    if not telegram_service.set_bot_description_sync(bot_profile.telegram_bot_token, normalized):
        raise HTTPException(status_code=502, detail="Telegram bot description sync failed")
    return True


def fetch_telegram_bot_description(bot_profile: BotProfile) -> str:
    token = (bot_profile.telegram_bot_token or "").strip()
    if not token or token == "CHANGE_ME":
        raise HTTPException(status_code=400, detail="Telegram Bot token is missing or still uses the placeholder value.")
    description = telegram_service.get_bot_description_sync(token)
    if description is None:
        raise HTTPException(status_code=502, detail="Telegram bot description fetch failed")
    return description


@router.get("", response_model=list[BotProfileResponse])
def list_bot_profiles(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
    tenant_id: str | None = None,
) -> list[BotProfile]:
    statement = select(BotProfile, Tenant.name).join(Tenant, Tenant.id == BotProfile.tenant_id)
    if is_super_admin(user):
        if tenant_id:
            statement = statement.where(BotProfile.tenant_id == UUID(tenant_id))
    else:
        statement = statement.where(BotProfile.tenant_id == user.tenant_id)

    rows = db.execute(statement.order_by(BotProfile.created_at.desc())).all()
    return [attach_tenant_name(bot_profile, tenant_name, db) for bot_profile, tenant_name in rows]


@router.get("/{bot_profile_id}/telegram-description", response_model=TelegramBotDescriptionResponse)
def get_bot_profile_telegram_description(
    bot_profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> TelegramBotDescriptionResponse:
    bot_profile = db.get(BotProfile, UUID(bot_profile_id))
    if not bot_profile:
        raise HTTPException(status_code=404, detail="Bot profile not found")
    ensure_tenant_access(user, bot_profile.tenant_id)
    return TelegramBotDescriptionResponse(description=fetch_telegram_bot_description(bot_profile))


@router.post("", response_model=BotProfileResponse)
def create_bot_profile(
    payload: BotProfileCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> BotProfile:
    tenant_id = payload.tenant_id or user.tenant_id
    ensure_tenant_access(user, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    create_values = payload.model_dump(exclude={"tenant_id", "telegram_bot_description"})
    create_values["unanswered_fallback_message"] = normalize_unanswered_fallback_message(
        create_values.get("unanswered_fallback_message")
    )
    create_values["email_auto_reply_message"] = normalize_email_auto_reply_message(
        create_values.get("email_auto_reply_message")
    )
    bot_profile = BotProfile(
        tenant_id=tenant_id,
        **create_values,
    )
    if not bot_profile.faq_hint_keywords_json:
        bot_profile.faq_hint_keywords_json = list(DEFAULT_FAQ_HINT_KEYWORDS)
    if not bot_profile.high_risk_keywords_json:
        bot_profile.high_risk_keywords_json = list(DEFAULT_HIGH_RISK_KEYWORDS)
    if not bot_profile.sensitive_keywords_json:
        bot_profile.sensitive_keywords_json = list(DEFAULT_SENSITIVE_KEYWORDS)
    if not bot_profile.welcome_message or not bot_profile.welcome_message.strip():
        bot_profile.welcome_message = DEFAULT_BOT_WELCOME_MESSAGE
    if not bot_profile.unanswered_fallback_message or not bot_profile.unanswered_fallback_message.strip():
        bot_profile.unanswered_fallback_message = DEFAULT_UNANSWERED_FALLBACK_MESSAGE
    if not bot_profile.email_auto_reply_message or not bot_profile.email_auto_reply_message.strip():
        bot_profile.email_auto_reply_message = DEFAULT_EMAIL_AUTO_REPLY_MESSAGE
    db.add(bot_profile)
    db.flush()

    style_profile = StyleProfile(
        tenant_id=bot_profile.tenant_id,
        bot_profile_id=bot_profile.id,
        tone="professional, warm, concise",
        persona_notes="Use concise Chinese, do not mention being an AI.",
        banned_phrases_json=["作为 AI", "根据系统", "机器人回复"],
        delay_min_ms=1200,
        delay_max_ms=2800,
        typing_enabled=True,
        clarify_max_turns=1,
    )
    db.add(style_profile)

    try:
        webhook_url = register_telegram_webhook(bot_profile)
        description_synced = sync_telegram_bot_description(bot_profile, payload.telegram_bot_description)
    except HTTPException:
        db.rollback()
        raise

    audit_service.record(
        db=db,
        tenant_id=str(bot_profile.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="bot_profile.created",
        target_type="bot_profile",
        target_id=str(bot_profile.id),
        detail_json={
            "telegram_bot_username": bot_profile.telegram_bot_username,
            "support_group_chat_id": bot_profile.support_group_chat_id,
            "welcome_message": bot_profile.welcome_message,
            "unanswered_fallback_message": bot_profile.unanswered_fallback_message,
            "email_auto_reply_enabled": bot_profile.email_auto_reply_enabled,
            "email_auto_reply_message": bot_profile.email_auto_reply_message,
            "faq_hint_keywords_json": bot_profile.faq_hint_keywords_json,
            "high_risk_keywords_json": bot_profile.high_risk_keywords_json,
            "sensitive_keywords_json": bot_profile.sensitive_keywords_json,
            "is_active": bot_profile.is_active,
            "telegram_webhook_url": webhook_url,
            "telegram_bot_description_synced": description_synced,
        },
    )
    db.commit()
    db.refresh(bot_profile)
    return attach_tenant_name(bot_profile, tenant.name, db)


@router.patch("/{bot_profile_id}", response_model=BotProfileResponse)
def update_bot_profile(
    bot_profile_id: str,
    payload: BotProfileUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> BotProfile:
    bot_profile = db.get(BotProfile, UUID(bot_profile_id))
    if not bot_profile:
        raise HTTPException(status_code=404, detail="Bot profile not found")
    ensure_tenant_access(user, bot_profile.tenant_id)

    updates = payload.model_dump(exclude_unset=True, exclude={"telegram_bot_description"})
    if "welcome_message" in updates and updates["welcome_message"] is not None and not updates["welcome_message"].strip():
        updates["welcome_message"] = DEFAULT_BOT_WELCOME_MESSAGE
    if "unanswered_fallback_message" in updates:
        updates["unanswered_fallback_message"] = normalize_unanswered_fallback_message(
            updates.get("unanswered_fallback_message")
        )
    if "email_auto_reply_message" in updates:
        updates["email_auto_reply_message"] = normalize_email_auto_reply_message(
            updates.get("email_auto_reply_message")
        )
    if "tenant_id" in updates and updates["tenant_id"] != bot_profile.tenant_id:
        raise HTTPException(status_code=409, detail="现有机器人不支持直接变更所属租户，请在目标租户中新建机器人")
    if "tenant_id" in updates:
        ensure_tenant_access(user, updates["tenant_id"])
        tenant = db.get(Tenant, updates["tenant_id"])
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
    for key, value in updates.items():
        setattr(bot_profile, key, value)
    audit_updates = payload.model_dump(exclude_unset=True, exclude={"telegram_bot_description"}, mode="json")
    audit_updates.pop("telegram_bot_token", None)
    try:
        webhook_url = register_telegram_webhook(bot_profile)
        description_synced = sync_telegram_bot_description(bot_profile, payload.telegram_bot_description)
    except HTTPException:
        db.rollback()
        raise
    audit_updates["telegram_webhook_url"] = webhook_url
    audit_updates["telegram_bot_description_synced"] = description_synced

    audit_service.record(
        db=db,
        tenant_id=str(bot_profile.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="bot_profile.updated",
        target_type="bot_profile",
        target_id=str(bot_profile.id),
        detail_json=audit_updates,
    )
    db.commit()
    db.refresh(bot_profile)
    tenant_name = db.scalar(select(Tenant.name).where(Tenant.id == bot_profile.tenant_id))
    return attach_tenant_name(bot_profile, tenant_name, db)


@router.delete("/{bot_profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bot_profile(
    bot_profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> Response:
    bot_profile = db.get(BotProfile, UUID(bot_profile_id))
    if not bot_profile:
        raise HTTPException(status_code=404, detail="Bot profile not found")
    ensure_tenant_access(user, bot_profile.tenant_id)

    try:
        webhook_delete_result = unregister_telegram_webhook(bot_profile)
    except HTTPException:
        db.rollback()
        raise

    knowledge_page_ids = list(
        db.scalars(select(KnowledgePage.id).where(KnowledgePage.bot_profile_id == bot_profile.id)).all()
    )
    conversation_ids = list(
        db.scalars(select(Conversation.id).where(Conversation.bot_profile_id == bot_profile.id)).all()
    )

    if knowledge_page_ids:
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_page_id.in_(knowledge_page_ids)))
    if conversation_ids:
        db.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
        db.execute(delete(HandoffTicket).where(HandoffTicket.conversation_id.in_(conversation_ids)))

    db.execute(delete(FAQEntry).where(FAQEntry.bot_profile_id == bot_profile.id))
    db.execute(delete(KnowledgePage).where(KnowledgePage.bot_profile_id == bot_profile.id))
    db.execute(delete(StyleProfile).where(StyleProfile.bot_profile_id == bot_profile.id))
    db.execute(delete(PromptTemplate).where(PromptTemplate.bot_profile_id == bot_profile.id))
    db.execute(delete(TelegramBusinessConnection).where(TelegramBusinessConnection.bot_profile_id == bot_profile.id))
    db.execute(delete(Conversation).where(Conversation.bot_profile_id == bot_profile.id))

    audit_service.record(
        db=db,
        tenant_id=str(bot_profile.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="bot_profile.deleted",
        target_type="bot_profile",
        target_id=str(bot_profile.id),
        detail_json={
            "telegram_bot_username": bot_profile.telegram_bot_username,
            "telegram_webhook_deleted": webhook_delete_result,
            "deleted_knowledge_pages": len(knowledge_page_ids),
            "deleted_conversations": len(conversation_ids),
        },
    )
    db.delete(bot_profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
