from __future__ import annotations

from sqlalchemy import or_, select

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.app.core.account_utils import slugify_login_username
from backend.api.app.core.config import get_settings
from backend.api.app.core.defaults import DEFAULT_BOT_WELCOME_MESSAGE, DEFAULT_EMAIL_AUTO_REPLY_MESSAGE, DEFAULT_UNANSWERED_FALLBACK_MESSAGE
from backend.api.app.core.logging import configure_logging
from backend.api.app.core.security import get_password_hash
from backend.api.app.db.base import Base
from backend.api.app.db.models.entities import BotProfile, StyleProfile, Tenant, User, UserRole
from backend.api.app.db.session import SessionLocal, engine
from backend.api.app.routers import auth, bot_profiles, conversations, faqs, knowledge_pages, media, style_profiles, telegram, tenants

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(telegram.router)
app.include_router(conversations.router)
app.include_router(bot_profiles.router)
app.include_router(tenants.router)
app.include_router(faqs.router)
app.include_router(knowledge_pages.router)
app.include_router(media.router)
app.include_router(style_profiles.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def on_startup() -> None:
    settings.validate_production()
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    if settings.bootstrap_demo_data:
        bootstrap_defaults()


def bootstrap_defaults() -> None:
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.name == settings.default_tenant_name))
        if not tenant:
            tenant = Tenant(name=settings.default_tenant_name, status="active")
            db.add(tenant)
            db.flush()

        bot = db.scalar(select(BotProfile).where(BotProfile.tenant_id == tenant.id))
        if not bot:
            bot = BotProfile(
                tenant_id=tenant.id,
                name=settings.default_bot_name,
                telegram_bot_token="CHANGE_ME",
                telegram_bot_username=None,
                support_group_chat_id=settings.default_support_group_chat_id,
                welcome_message=DEFAULT_BOT_WELCOME_MESSAGE,
                unanswered_fallback_message=DEFAULT_UNANSWERED_FALLBACK_MESSAGE,
                email_auto_reply_enabled=True,
                email_auto_reply_message=DEFAULT_EMAIL_AUTO_REPLY_MESSAGE,
                language="zh",
                industry="saas",
                faq_hint_keywords_json=["价格", "套餐", "试用", "功能", "支持"],
                high_risk_keywords_json=["人工", "投诉", "退款", "退费", "律师", "举报"],
                sensitive_keywords_json=["骂", "骗", "垃圾", "诈骗"],
                working_hours_json={},
                forbidden_topics_json=[],
                is_active=True,
            )
            db.add(bot)
            db.flush()
        else:
            changed = False
            if not bot.faq_hint_keywords_json:
                bot.faq_hint_keywords_json = ["价格", "套餐", "试用", "功能", "支持"]
                changed = True
            if not bot.high_risk_keywords_json:
                bot.high_risk_keywords_json = ["人工", "投诉", "退款", "退费", "律师", "举报"]
                changed = True
            if not bot.sensitive_keywords_json:
                bot.sensitive_keywords_json = ["骂", "骗", "垃圾", "诈骗"]
                changed = True
            if not bot.welcome_message:
                bot.welcome_message = DEFAULT_BOT_WELCOME_MESSAGE
                changed = True
            if not bot.unanswered_fallback_message:
                bot.unanswered_fallback_message = DEFAULT_UNANSWERED_FALLBACK_MESSAGE
                changed = True
            if not bot.email_auto_reply_message:
                bot.email_auto_reply_message = DEFAULT_EMAIL_AUTO_REPLY_MESSAGE
                changed = True
            if changed:
                db.add(bot)

        style = db.scalar(select(StyleProfile).where(StyleProfile.bot_profile_id == bot.id))
        if not style:
            style = StyleProfile(
                tenant_id=tenant.id,
                bot_profile_id=bot.id,
                tone="professional, warm, concise",
                persona_notes="Use concise Chinese, do not mention being an AI.",
                banned_phrases_json=["作为 AI", "根据系统", "机器人回复"],
                delay_min_ms=1200,
                delay_max_ms=2800,
                typing_enabled=True,
                clarify_max_turns=1,
            )
            db.add(style)

        admin_login_username = slugify_login_username(settings.default_tenant_name)
        admin = db.scalar(
            select(User).where(or_(User.email == settings.default_admin_email, User.login_username == admin_login_username))
        )
        if not admin:
            admin = User(
                tenant_id=tenant.id,
                login_username=admin_login_username,
                email=settings.default_admin_email,
                password_hash=get_password_hash(settings.default_admin_password),
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(admin)
        else:
            changed = False
            if not admin.tenant_id:
                admin.tenant_id = tenant.id
                changed = True
            if not admin.login_username:
                admin.login_username = admin_login_username
                changed = True
            if changed:
                db.add(admin)

        super_admin = db.scalar(
            select(User).where(or_(User.email == settings.default_super_admin_email, User.login_username == "superadmin"))
        )
        if not super_admin:
            super_admin = User(
                tenant_id=None,
                login_username="superadmin",
                email=settings.default_super_admin_email,
                password_hash=get_password_hash(settings.default_super_admin_password),
                role=UserRole.SUPER_ADMIN,
                is_active=True,
            )
            db.add(super_admin)
        else:
            changed = False
            if super_admin.tenant_id is not None:
                super_admin.tenant_id = None
                changed = True
            if not super_admin.login_username:
                super_admin.login_username = "superadmin"
                changed = True
            if changed:
                db.add(super_admin)

        db.commit()
    finally:
        db.close()
