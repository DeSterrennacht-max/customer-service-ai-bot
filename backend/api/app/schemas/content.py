from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from backend.api.app.core.defaults import DEFAULT_BOT_WELCOME_MESSAGE
from backend.api.app.db.models.entities import RiskLevel
from backend.api.app.schemas.common import BaseResponse


class FAQBase(BaseModel):
    question_patterns_json: list[str] = Field(default_factory=list)
    canonical_answer: str
    answer_style_notes: str | None = None
    category: str | None = None
    product_scope: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    priority: int = 100
    status: str = "active"


class FAQCreate(FAQBase):
    bot_profile_id: UUID
    tenant_id: UUID | None = None


class FAQUpdate(BaseModel):
    question_patterns_json: list[str] | None = None
    canonical_answer: str | None = None
    answer_style_notes: str | None = None
    category: str | None = None
    product_scope: str | None = None
    risk_level: RiskLevel | None = None
    priority: int | None = None
    status: str | None = None


class FAQResponse(BaseResponse, FAQBase):
    tenant_id: UUID
    bot_profile_id: UUID
    updated_at: datetime


class KnowledgePageBase(BaseModel):
    title: str
    body_markdown: str
    tags_json: list[str] = Field(default_factory=list)
    product_scope: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    status: str = "active"


class KnowledgePageCreate(KnowledgePageBase):
    bot_profile_id: UUID
    tenant_id: UUID | None = None


class KnowledgePageUpdate(BaseModel):
    title: str | None = None
    body_markdown: str | None = None
    tags_json: list[str] | None = None
    product_scope: str | None = None
    risk_level: RiskLevel | None = None
    status: str | None = None


class KnowledgePageResponse(BaseResponse, KnowledgePageBase):
    tenant_id: UUID
    bot_profile_id: UUID
    updated_at: datetime


class StyleProfileUpdate(BaseModel):
    tone: str | None = None
    persona_notes: str | None = None
    banned_phrases_json: list[str] | None = None
    delay_min_ms: int | None = None
    delay_max_ms: int | None = None
    typing_enabled: bool | None = None
    clarify_max_turns: int | None = None


class StyleProfileResponse(BaseResponse):
    tenant_id: UUID
    bot_profile_id: UUID
    tone: str
    persona_notes: str | None = None
    banned_phrases_json: list[str] | None = None
    delay_min_ms: int
    delay_max_ms: int
    typing_enabled: bool
    clarify_max_turns: int
    updated_at: datetime


class BotProfileBase(BaseModel):
    name: str
    telegram_bot_token: str
    telegram_bot_username: str | None = None
    support_group_chat_id: str | None = None
    welcome_message: str = DEFAULT_BOT_WELCOME_MESSAGE
    language: str = "zh"
    industry: str | None = None
    faq_hint_keywords_json: list[str] = Field(default_factory=list)
    high_risk_keywords_json: list[str] = Field(default_factory=list)
    sensitive_keywords_json: list[str] = Field(default_factory=list)
    is_active: bool = True


class BotProfileCreate(BotProfileBase):
    tenant_id: UUID | None = None


class BotProfileUpdate(BaseModel):
    tenant_id: UUID | None = None
    name: str | None = None
    telegram_bot_token: str | None = None
    telegram_bot_username: str | None = None
    support_group_chat_id: str | None = None
    welcome_message: str | None = None
    language: str | None = None
    industry: str | None = None
    faq_hint_keywords_json: list[str] | None = None
    high_risk_keywords_json: list[str] | None = None
    sensitive_keywords_json: list[str] | None = None
    is_active: bool | None = None


class BotProfileResponse(BaseResponse, BotProfileBase):
    tenant_id: UUID
    tenant_name: str | None = None


class TenantResponse(BaseResponse):
    name: str
    admin_login_username: str | None = None
    status: str
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class TenantCreate(BaseModel):
    name: str
    login_username: str
    status: str = "active"
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class TenantUpdate(BaseModel):
    name: str
    login_username: str | None = None
    status: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class TenantCreateResponse(TenantResponse):
    temporary_password: str


class TenantAdminPasswordResetResponse(BaseModel):
    tenant_id: UUID
    admin_login_username: str
    temporary_password: str
