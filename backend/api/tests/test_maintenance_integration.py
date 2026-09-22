"""Run against the isolated csb_test PostgreSQL database after `alembic upgrade head`."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.api.app.core.config import get_settings
from backend.api.app.core.security import get_password_hash
from backend.api.app.db.models.entities import (
    AuthSession, BotProfile, Conversation, ConversationStatus, DeliveryStatus, FAQEntry,
    HandoffStatus, HandoffTicket, KnowledgePage, LoginThrottle, Message, MessageChannel,
    MessageSource, OutboundDelivery, RiskLevel, StyleProfile, TelegramUpdate, Tenant, User, UserRole,
)
from backend.api.app.db.session import SessionLocal, engine, get_db
from backend.api.app.dependencies import get_current_user
from backend.api.app.main import app
from backend.api.app.routers.auth import change_password, login, logout, refresh_tokens
from backend.api.app.routers.bot_profiles import update_bot_profile
from backend.api.app.routers.conversations import retry_delivery, takeover_conversation
from backend.api.app.routers.telegram import accept_update, process_received_update
from backend.api.app.routers.tenants import reset_tenant_admin_password
from backend.api.app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshTokenRequest
from backend.api.app.schemas.content import BotProfileUpdate
from backend.api.app.schemas.conversation import RetryDeliveryRequest
from backend.api.app.schemas.telegram import TelegramWebhookPayload
from backend.api.app.services.delivery_service import deliver_locked, queue_message, recover_interrupted_deliveries
from backend.api.app.services.response_service import ResponseService
from backend.worker.app.tasks.process_incoming_message import process_update

pytestmark = pytest.mark.skipif(os.getenv("CSB_INTEGRATION_TESTS") != "1", reason="requires isolated PostgreSQL")


@pytest.fixture
def db():
    assert get_settings().app_env == "test" and engine.url.database == "csb_test", "Refusing to use a non-test database"
    with SessionLocal() as session:
        yield session
        session.rollback()


@pytest.fixture
def context(db):
    tenant = Tenant(name=f"test-{uuid4()}", status="active")
    db.add(tenant)
    db.flush()
    user = User(tenant_id=tenant.id, login_username=f"test-{uuid4()}", role=UserRole.ADMIN,
                password_hash=get_password_hash("OriginalPassword123"), is_active=True)
    bot = BotProfile(tenant_id=tenant.id, name="Test", telegram_bot_token="123456:fake_token_for_isolated_tests_only",
                     support_group_chat_id=f"-{uuid4().int % 10000000000}", is_active=True,
                     high_risk_keywords_json=[], sensitive_keywords_json=[])
    db.add_all([bot, user])
    db.flush()
    db.add(StyleProfile(tenant_id=tenant.id, bot_profile_id=bot.id, typing_enabled=False))
    db.commit()
    return tenant, bot, user


def conversation(db, context, *, business=False):
    tenant, bot, _ = context
    row = Conversation(tenant_id=tenant.id, bot_profile_id=bot.id, telegram_chat_id="42", telegram_user_id="42",
                       telegram_business_connection_id="connection-test" if business else None)
    db.add(row)
    db.commit()
    return row


def payload(update_id=1, message_id=1, chat_id="42", text="/start"):
    return TelegramWebhookPayload(update_id=update_id, message={"message_id": message_id,
        "chat": {"id": chat_id, "type": "private"}, "from": {"id": 42}, "text": text})


def count(db, model, condition):
    return db.scalar(select(func.count()).select_from(model).where(condition))


def outbound(db, context, *, photos=False, automatic=False):
    conv = conversation(db, context)
    message = Message(tenant_id=conv.tenant_id, conversation_id=conv.id, source=MessageSource.BOT,
                      channel=MessageChannel.TELEGRAM_DM, content_text="hello")
    db.add(message)
    queue_message(db, conv, message, "42", text="hello", automatic=automatic,
                  image_assets=[{"url": "https://media.example.com/test.png"}] if photos else [])
    db.commit()
    items = list(db.scalars(select(OutboundDelivery).where(OutboundDelivery.message_id == message.id)
                           .order_by(OutboundDelivery.sequence)).all())
    return conv, message, items


def test_http_webhook_persists_once_without_running_pipeline(db, context, monkeypatch):
    _, bot, _ = context
    def forbidden(*args, **kwargs):
        raise AssertionError("Webhook must not run message processing")
    monkeypatch.setattr(ResponseService, "handle_customer_message", forbidden)
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            url = f"/telegram/webhook/{bot.id}"
            data = payload().model_dump()
            assert client.post(url, json=data).status_code == 401
            headers = {"X-Telegram-Bot-Api-Secret-Token": get_settings().webhook_secret}
            assert client.post(url, json=data, headers=headers).json()["status"] == "accepted"
            assert client.post(url, json=data, headers=headers).json()["reason"] == "duplicate_update"
            assert client.post(url, json={"message": {}}, headers=headers).status_code == 400
    finally:
        app.dependency_overrides.clear()
    assert count(db, TelegramUpdate, TelegramUpdate.bot_profile_id == bot.id) == 1
    assert count(db, OutboundDelivery, OutboundDelivery.bot_profile_id == bot.id) == 0


def test_inbox_processing_is_idempotent_and_atomic(db, context):
    _, bot, _ = context
    accept_update(db, payload(), str(bot.id))
    record = db.scalar(select(TelegramUpdate).where(TelegramUpdate.bot_profile_id == bot.id))
    assert process_update(db, record.id) == "processed"
    assert process_update(db, record.id) == "not_due"
    # Different update IDs referring to the same customer message also must not resend.
    accept_update(db, payload(update_id=2), str(bot.id))
    second = db.scalar(select(TelegramUpdate).where(TelegramUpdate.bot_profile_id == bot.id, TelegramUpdate.update_id == 2))
    assert process_update(db, second.id) == "processed"
    assert count(db, OutboundDelivery, OutboundDelivery.bot_profile_id == bot.id) == 1
    assert count(db, Conversation, Conversation.bot_profile_id == bot.id) == 1


def test_concurrent_duplicate_receipts_and_workers(db, context):
    from concurrent.futures import ThreadPoolExecutor
    bot_id = context[1].id
    def receive(_):
        with SessionLocal() as other:
            return accept_update(other, payload(), str(bot_id))["status"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(receive, range(2))) == ["accepted", "ignored"]
    record_id = db.scalar(select(TelegramUpdate.id).where(TelegramUpdate.bot_profile_id == bot_id))
    db.commit()
    def process(_):
        with SessionLocal() as other:
            return process_update(other, record_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(process, range(2)))
    assert results.count("processed") == 1
    assert count(db, OutboundDelivery, OutboundDelivery.bot_profile_id == bot_id) == 1


def test_pipeline_failure_rolls_back_customer_and_outbox_together(db, context, monkeypatch):
    bot_id = context[1].id
    accept_update(db, payload(), str(bot_id))
    record = db.scalar(select(TelegramUpdate).where(TelegramUpdate.bot_profile_id == bot_id))
    original = ResponseService.dispatch_reply
    def fail_after_queue(service, *args, **kwargs):
        original(service, *args, **kwargs)
        raise RuntimeError("Simulated failure before commit")
    monkeypatch.setattr(ResponseService, "dispatch_reply", fail_after_queue)
    with pytest.raises(RuntimeError): process_update(db, record.id)
    db.rollback()
    assert count(db, Conversation, Conversation.bot_profile_id == bot_id) == 0
    assert count(db, OutboundDelivery, OutboundDelivery.bot_profile_id == bot_id) == 0
    db.refresh(record)
    assert record.status == "pending"


def test_same_update_id_belongs_to_each_bot(db, context):
    tenant, bot, _ = context
    second = BotProfile(tenant_id=tenant.id, name="Second", telegram_bot_token="123456:other_test_token")
    db.add(second)
    db.commit()
    assert accept_update(db, payload(), str(bot.id))["status"] == "accepted"
    assert accept_update(db, payload(), str(second.id))["status"] == "accepted"


def test_manual_takeover_queues_one_support_notification(db, context):
    _, bot, user = context
    conv = conversation(db, context)
    takeover_conversation(str(conv.id), db=db, user=user)
    takeover_conversation(str(conv.id), db=db, user=user)
    ticket = db.get(HandoffTicket, conv.handoff_ticket_id)
    assert conv.status == ConversationStatus.HANDOFF
    assert ticket.group_chat_id == bot.support_group_chat_id
    assert count(db, OutboundDelivery, OutboundDelivery.bot_profile_id == bot.id) == 1


def test_business_handoff_suppresses_email_and_faq_replies(db, context):
    _, bot, user = context
    conv = conversation(db, context, business=True)
    takeover_conversation(str(conv.id), db=db, user=user)
    _, result = ResponseService().handle_business_customer_message(db, bot, conv, "42", "42", None,
        "connection-test", "test@example.com", {}, "7")
    db.commit()
    assert result.action == "handoff" and result.text == ""
    assert count(db, Message, (Message.conversation_id == conv.id) & (Message.source == MessageSource.BOT)) == 0


@pytest.mark.parametrize("knowledge", [False, True])
def test_high_risk_knowledge_transfers_regular_chat(db, context, knowledge):
    tenant, bot, _ = context
    conv = conversation(db, context)
    if knowledge:
        db.add(KnowledgePage(tenant_id=tenant.id, bot_profile_id=bot.id, title="special policy", body_markdown="Manual review required", risk_level=RiskLevel.HIGH))
    else:
        db.add(FAQEntry(tenant_id=tenant.id, bot_profile_id=bot.id, question_patterns_json=["special policy"], canonical_answer="Manual review required", risk_level=RiskLevel.HIGH))
    db.commit()
    result = ResponseService().handle_customer_message(db, conv, "special policy", {}, "8")
    assert result.action == "handoff" and result.risk_level == "high"
    assert result.intent == "high_risk_knowledge"


def test_high_risk_faq_never_auto_replies_in_business(db, context):
    tenant, bot, _ = context
    db.add(FAQEntry(tenant_id=tenant.id, bot_profile_id=bot.id, question_patterns_json=["special policy"], canonical_answer="Manual review required", risk_level=RiskLevel.HIGH))
    db.commit()
    conv, result = ResponseService().handle_business_customer_message(db, bot, None, "42", "42", None,
        "connection-test", "special policy", {}, "9")
    assert conv is None and result.action == "ignored" and result.risk_level == "high"


def test_group_ids_are_scoped_to_bot_and_group(db, context):
    tenant, first, user = context
    second = BotProfile(tenant_id=tenant.id, name="Other", telegram_bot_token="123456:other", support_group_chat_id="-202")
    db.add(second)
    db.commit()
    for bot in (first, second):
        conv = conversation(db, (tenant, bot, user))
        conv.status = ConversationStatus.HANDOFF
        ticket = HandoffTicket(tenant_id=tenant.id, conversation_id=conv.id, group_chat_id=bot.support_group_chat_id,
            group_thread_key="300", reason="manual_takeover", summary_text="help", status=HandoffStatus.ACTIVE)
        db.add(ticket)
        db.flush()
        conv.handoff_ticket_id = ticket.id
        update = TelegramWebhookPayload(update_id=4, message={"message_id": 500, "chat": {"id": bot.support_group_chat_id, "type": "supergroup"},
             "from": {"id": 1}, "text": "support reply", "reply_to_message": {"message_id": 300}})
        assert process_received_update(db, update, bot)["handled"] is True
        db.commit()
        assert process_received_update(db, update, bot)["reason"] == "duplicate_group_message"
    assert count(db, Message, (Message.tenant_id == tenant.id) & (Message.source == MessageSource.AGENT)) == 2
    # A different bot in the same group must not pick up the first bot's ticket.
    update.message["chat"]["id"] = first.support_group_chat_id
    update.message["message_id"] = 501
    assert process_received_update(db, update, second)["handled"] is False


def test_known_retry_and_partial_retry_do_not_resend_successful_parts(db, context):
    conv, message, items = outbound(db, context, photos=True)
    method = SendMessage(chat_id="42", text="hello")
    def throttled(*args): raise TelegramRetryAfter(method=method, message="rate limited", retry_after=1)
    assert deliver_locked(db, items[0].id, sender=throttled) == "pending"
    items[0].next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert deliver_locked(db, items[0].id, sender=lambda *args: 101) == "sent"
    def forbidden(*args): raise TelegramForbiddenError(method=method, message="not allowed")
    assert deliver_locked(db, items[1].id, sender=forbidden) == "failed"
    assert message.delivery_status == DeliveryStatus.PARTIAL
    retry_delivery(conv.id, message.id, RetryDeliveryRequest(), db=db, user=context[2])
    assert items[0].status == "sent" and items[1].status == "pending"
    assert deliver_locked(db, items[1].id, sender=lambda *args: 102) == "sent"
    assert message.delivery_status == DeliveryStatus.SENT


def test_unknown_network_outcome_requires_explicit_review(db, context):
    conv, message, items = outbound(db, context)
    def timeout(*args): raise TimeoutError()
    assert deliver_locked(db, items[0].id, sender=timeout) == "uncertain"
    assert deliver_locked(db, items[0].id, sender=lambda *args: pytest.fail("must not auto-resend")) == "not_due"
    with pytest.raises(HTTPException) as exc:
        retry_delivery(conv.id, message.id, RetryDeliveryRequest(), db=db, user=context[2])
    assert exc.value.status_code == 409
    retry_delivery(conv.id, message.id, RetryDeliveryRequest(confirm_uncertain=True), db=db, user=context[2])
    assert deliver_locked(db, items[0].id, sender=lambda *args: 103) == "sent"


def test_takeover_cancels_queued_automatic_reply(db, context):
    conv, message, items = outbound(db, context, automatic=True)
    conv.status = ConversationStatus.HANDOFF
    db.commit()
    assert deliver_locked(db, items[0].id, sender=lambda *args: pytest.fail("must not send")) == "cancelled"


def test_interrupted_preparation_is_retryable_but_interrupted_send_is_not(db, context):
    _, message, items = outbound(db, context, photos=True)
    for item, state in zip(items, ["preparing", "sending"]):
        item.status = state
        item.started_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    db.commit()
    recover_interrupted_deliveries(db)
    assert items[0].status == "pending" and items[1].status == "uncertain"


def test_refresh_rotation_password_change_and_logout_revoke_sessions(db, context):
    _, _, user = context
    initial = login(LoginRequest(username=user.login_username, password="OriginalPassword123"), db=db)
    assert get_current_user(initial.access_token, db=db).id == user.id
    rotated = refresh_tokens(RefreshTokenRequest(refresh_token=initial.refresh_token), db=db)
    with pytest.raises(HTTPException):
        refresh_tokens(RefreshTokenRequest(refresh_token=initial.refresh_token), db=db)
    change_password(ChangePasswordRequest(current_password="OriginalPassword123", new_password="UpdatedPassword123"), user=user, db=db)
    with pytest.raises(HTTPException): get_current_user(rotated.access_token, db=db)
    with pytest.raises(HTTPException): refresh_tokens(RefreshTokenRequest(refresh_token=rotated.refresh_token), db=db)
    fresh = login(LoginRequest(username=user.login_username, password="UpdatedPassword123"), db=db)
    logout(RefreshTokenRequest(refresh_token=fresh.refresh_token), db=db)
    with pytest.raises(HTTPException): get_current_user(fresh.access_token, db=db)


def test_admin_reset_revokes_access_and_refresh(db, context):
    tenant, _, user = context
    initial = login(LoginRequest(username=user.login_username, password="OriginalPassword123"), db=db)
    operator = User(id=uuid4(), role=UserRole.SUPER_ADMIN)
    result = reset_tenant_admin_password(str(tenant.id), db=db, user=operator)
    with pytest.raises(HTTPException): get_current_user(initial.access_token, db=db)
    with pytest.raises(HTTPException): refresh_tokens(RefreshTokenRequest(refresh_token=initial.refresh_token), db=db)
    assert login(LoginRequest(username=user.login_username, password=result.temporary_password), db=db).access_token


def test_login_rate_limit_survives_failed_requests(db, context):
    user = context[2]
    for _ in range(get_settings().login_attempt_limit):
        with pytest.raises(HTTPException) as exc:
            login(LoginRequest(username=user.login_username, password="wrong"), db=db)
        assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        login(LoginRequest(username=user.login_username, password="OriginalPassword123"), db=db)
    assert exc.value.status_code == 429


def test_bot_transfer_rejected_before_external_side_effects(db, context, monkeypatch):
    from backend.api.app.routers import bot_profiles
    tenant, bot, _ = context
    other = Tenant(name="target")
    db.add(other)
    db.commit()
    monkeypatch.setattr(bot_profiles, "register_telegram_webhook", lambda *args: pytest.fail("must not register"))
    with pytest.raises(HTTPException) as exc:
        update_bot_profile(str(bot.id), BotProfileUpdate(tenant_id=other.id), db=db, user=User(role=UserRole.SUPER_ADMIN))
    assert exc.value.status_code == 409 and bot.tenant_id == tenant.id


def test_scheduled_release_uses_real_database(db, context):
    from backend.worker.app.tasks.release_stale_handoffs import release_stale_handoffs
    conv = conversation(db, context)
    takeover_conversation(str(conv.id), db=db, user=context[2])
    conv.last_customer_message_at = datetime.now(timezone.utc) - timedelta(hours=9)
    db.commit()
    result = release_stale_handoffs()
    db.refresh(conv)
    assert str(conv.id) in result["conversation_ids"]
    assert conv.status == ConversationStatus.OPEN


def test_operator_recovery_revokes_superadmin_sessions(db, monkeypatch, capsys):
    from backend.api.app import cli
    from backend.api.app.core.security import verify_password
    user = User(login_username=f"super-{uuid4()}", role=UserRole.SUPER_ADMIN,
                password_hash=get_password_hash("OriginalPassword123"), is_active=True)
    db.add(user)
    db.commit()
    initial = login(LoginRequest(username=user.login_username, password="OriginalPassword123"), db=db)
    monkeypatch.setattr("sys.argv", ["recovery", "reset-superadmin", "--username", user.login_username])
    monkeypatch.setattr(cli, "getpass", lambda prompt: "RecoveredPassword123")
    cli.main()
    db.refresh(user)
    assert verify_password("RecoveredPassword123", user.password_hash)
    with pytest.raises(HTTPException): get_current_user(initial.access_token, db=db)
    assert "RecoveredPassword123" not in capsys.readouterr().out
