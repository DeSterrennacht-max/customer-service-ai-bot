from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.app.core.defaults import DEFAULT_BOT_WELCOME_MESSAGE, DEFAULT_EMAIL_AUTO_REPLY_MESSAGE, DEFAULT_UNANSWERED_FALLBACK_MESSAGE
from backend.api.app.db.models.entities import BotProfile, Conversation, ConversationStatus, DeliveryStatus, Message, MessageChannel, MessageSource, RiskLevel, StyleProfile
from backend.api.app.llm.generator_client import GeneratorLLMClient
from backend.api.app.services.audit_service import AuditService
from backend.api.app.services.conversation_service import ConversationService
from backend.api.app.services.handoff_service import HandoffService
from backend.api.app.services.knowledge_service import KnowledgeService, RetrievedKnowledge
from backend.api.app.services.rule_router import RuleRouteResult, RuleRouter
from backend.api.app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)

FOLLOWUP_QUANTITY_PATTERN = re.compile(r"(\d+|[一二两三四五六七八九十])\s*(个|位|席|坐席|人|账号|用户|台)?")
FOLLOWUP_HINT_WORDS = ("这个", "那个", "这样", "这种", "那种", "继续", "然后", "上面", "刚才")
UNANSWERED_HANDOFF_NOTICE = DEFAULT_UNANSWERED_FALLBACK_MESSAGE


@dataclass(slots=True)
class PipelineResult:
    action: str
    text: str
    evidence: list[str]
    risk_level: str
    intent: str
    source_type: str = "none"
    structured: bool = False
    image_assets: list[dict[str, object]] = field(default_factory=list)


class ResponseService:
    def __init__(self) -> None:
        self.conversations = ConversationService()
        self.rules = RuleRouter()
        self.knowledge = KnowledgeService()
        self.handoff = HandoffService()
        self.telegram = TelegramService()
        self.generator = GeneratorLLMClient()
        self.audit = AuditService()

    def handle_customer_message(self, db: Session, conversation: Conversation, text: str, raw_payload: dict, telegram_message_id: str | None) -> PipelineResult:
        bot_profile = self.conversations.get_bot_profile(db, conversation.bot_profile_id) or self.conversations.get_default_bot_profile(db)
        self.conversations.record_message(
            db,
            conversation=conversation,
            source=MessageSource.CUSTOMER,
            channel=MessageChannel.TELEGRAM_DM,
            content_text=text,
            raw_payload_json=raw_payload,
            telegram_message_id=telegram_message_id,
        )

        if conversation.status == ConversationStatus.HANDOFF:
            self.handoff.sync_customer_message_to_group(db, conversation, text, bot_profile.telegram_bot_token)
            return PipelineResult(action="handoff", text="", evidence=[], risk_level="high", intent="human_request", source_type="handoff")

        rule_result = self.rules.route(text, bot_profile=bot_profile)
        if rule_result and rule_result.action == "handoff":
            return self._handoff(db, conversation, text, rule_result)
        if rule_result and rule_result.action == "welcome":
            return PipelineResult(
                action="template_reply",
                text=(bot_profile.welcome_message or DEFAULT_BOT_WELCOME_MESSAGE).strip(),
                evidence=["system:welcome"],
                risk_level=rule_result.risk_level,
                intent=rule_result.intent,
                source_type="system",
            )
        if rule_result and rule_result.action == "email_auto_reply":
            return PipelineResult(
                action="template_reply",
                text=self._email_auto_reply_message(bot_profile),
                evidence=["system:email_auto_reply"],
                risk_level=rule_result.risk_level,
                intent=rule_result.intent,
                source_type="email_auto_reply",
            )

        followup_first = self._looks_like_followup(text)
        if followup_first:
            answer_result = self._build_followup_result(db, conversation, text)
            if answer_result:
                return self._reply_or_handoff(db, conversation, text, answer_result)
        answer_result = self._build_answer_result(db, conversation, text, "faq")
        if answer_result:
            return self._reply_or_handoff(db, conversation, text, answer_result)
        if not followup_first:
            answer_result = self._build_followup_result(db, conversation, text)
            if answer_result:
                return self._reply_or_handoff(db, conversation, text, answer_result)
        answer_result = self._build_answer_result(db, conversation, text, "knowledge")
        if answer_result:
            return self._reply_or_handoff(db, conversation, text, answer_result)

        return self._handoff(
            db,
            conversation,
            text,
            RuleRouteResult(action="handoff", intent="unanswered", risk_level="medium"),
            customer_notice=self._unanswered_fallback_message(bot_profile),
        )

    def handle_business_customer_message(
        self,
        db: Session,
        bot_profile: BotProfile,
        conversation: Conversation | None,
        telegram_chat_id: str,
        telegram_user_id: str,
        display_name: str | None,
        business_connection_id: str,
        text: str,
        raw_payload: dict,
        telegram_message_id: str | None,
    ) -> tuple[Conversation | None, PipelineResult]:
        if conversation and conversation.status == ConversationStatus.HANDOFF:
            self.conversations.record_message(
                db, conversation=conversation, source=MessageSource.CUSTOMER,
                channel=MessageChannel.TELEGRAM_DM, content_text=text,
                raw_payload_json=raw_payload, telegram_message_id=telegram_message_id,
            )
            self.handoff.sync_customer_message_to_group(db, conversation, text, bot_profile.telegram_bot_token)
            return conversation, PipelineResult(action="handoff", text="", evidence=[], risk_level="high", intent="human_request", source_type="handoff")
        rule_result = self.rules.route(text, bot_profile=bot_profile)
        if rule_result and rule_result.action == "email_auto_reply":
            return self._record_business_reply_candidate(
                db=db,
                bot_profile=bot_profile,
                conversation=conversation,
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                display_name=display_name,
                business_connection_id=business_connection_id,
                text=text,
                raw_payload=raw_payload,
                telegram_message_id=telegram_message_id,
                answer_result=RetrievedKnowledge(
                    text=self._email_auto_reply_message(bot_profile),
                    evidence=["system:email_auto_reply"],
                    source_type="email_auto_reply",
                    structured=False,
                ),
            )
        if rule_result:
            return None, self._ignored_business_result(rule_result.intent, rule_result.risk_level)

        followup_first = bool(conversation and self._looks_like_followup(text))
        if followup_first and conversation:
            answer_result = self._build_followup_result(db, conversation, text)
            if answer_result:
                return self._record_business_reply_candidate(
                    db=db,
                    bot_profile=bot_profile,
                    conversation=conversation,
                    telegram_chat_id=telegram_chat_id,
                    telegram_user_id=telegram_user_id,
                    display_name=display_name,
                    business_connection_id=business_connection_id,
                    text=text,
                    raw_payload=raw_payload,
                    telegram_message_id=telegram_message_id,
                    answer_result=answer_result,
                )

        answer_result = self._retrieve_answer_result(db, bot_profile.id, text, "faq")
        if answer_result:
            return self._record_business_reply_candidate(
                db=db,
                bot_profile=bot_profile,
                conversation=conversation,
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                display_name=display_name,
                business_connection_id=business_connection_id,
                text=text,
                raw_payload=raw_payload,
                telegram_message_id=telegram_message_id,
                answer_result=answer_result,
            )

        if not followup_first and conversation:
            answer_result = self._build_followup_result(db, conversation, text)
            if answer_result:
                return self._record_business_reply_candidate(
                    db=db,
                    bot_profile=bot_profile,
                    conversation=conversation,
                    telegram_chat_id=telegram_chat_id,
                    telegram_user_id=telegram_user_id,
                    display_name=display_name,
                    business_connection_id=business_connection_id,
                    text=text,
                    raw_payload=raw_payload,
                    telegram_message_id=telegram_message_id,
                    answer_result=answer_result,
                )

        answer_result = self._retrieve_answer_result(db, bot_profile.id, text, "knowledge")
        if answer_result:
            return self._record_business_reply_candidate(
                db=db,
                bot_profile=bot_profile,
                conversation=conversation,
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                display_name=display_name,
                business_connection_id=business_connection_id,
                text=text,
                raw_payload=raw_payload,
                telegram_message_id=telegram_message_id,
                answer_result=answer_result,
            )

        return None, self._ignored_business_result("unanswered", "medium")

    def _reply_or_handoff(self, db: Session, conversation: Conversation, text: str, answer: RetrievedKnowledge) -> PipelineResult:
        if answer.risk_level == RiskLevel.HIGH:
            return self._handoff(db, conversation, text, RuleRouteResult(action="handoff", intent="high_risk_knowledge", risk_level="high"))
        is_knowledge = answer.source_type == "knowledge_page"
        return PipelineResult(
            action="knowledge_reply" if is_knowledge else "template_reply",
            text=answer.text, evidence=answer.evidence, risk_level=answer.risk_level.value,
            intent="knowledge" if is_knowledge else "faq", source_type=answer.source_type,
            structured=answer.structured, image_assets=answer.image_assets,
        )

    def dispatch_reply(self, db: Session, conversation: Conversation, pipeline_result: PipelineResult) -> str | None:
        """Persist the reply in the same transaction as the incoming message; never send here."""
        from backend.api.app.services.delivery_service import queue_message
        if pipeline_result.action == "ignored" or not (pipeline_result.text.strip() or pipeline_result.image_assets):
            return None
        message = self.conversations.record_message(
            db, conversation=conversation, source=MessageSource.BOT,
            channel=MessageChannel.TELEGRAM_DM, content_text=pipeline_result.text,
            raw_payload_json={"evidence": pipeline_result.evidence, "source_type": pipeline_result.source_type,
                              "image_assets": pipeline_result.image_assets},
            telegram_message_id=None, intent=pipeline_result.intent, risk_level=RiskLevel(pipeline_result.risk_level),
        )
        queue_message(db, conversation, message, conversation.telegram_chat_id,
                      text=pipeline_result.text, image_assets=pipeline_result.image_assets,
                      business_connection_id=getattr(conversation, "telegram_business_connection_id", None),
                      automatic=pipeline_result.action != "handoff",
                      humanize=pipeline_result.action != "handoff" and pipeline_result.source_type != "email_auto_reply",
                      structured=pipeline_result.structured)
        return pipeline_result.text

    def _handoff(
        self,
        db: Session,
        conversation: Conversation,
        text: str,
        rule_result: RuleRouteResult | None,
        customer_notice: str = "",
    ) -> PipelineResult:
        reason = rule_result.intent if rule_result else "needs_human"
        ticket = self.handoff.create_ticket(db, conversation, reason=reason, summary_text=text)
        bot_profile = self.conversations.get_bot_profile(db, conversation.bot_profile_id) or self.conversations.get_default_bot_profile(db)
        self.handoff.notify_support_group(db, ticket, conversation, bot_profile.telegram_bot_token, bot_profile.support_group_chat_id)
        return PipelineResult(
            action="handoff",
            text=customer_notice,
            evidence=[f"handoff:{ticket.id}"],
            risk_level="high",
            intent=reason,
            source_type="handoff",
        )

    def _build_answer(self, db: Session, conversation: Conversation, text: str, intent: str) -> tuple[str, list[str], str, bool]:
        result = self._build_answer_result(db, conversation, text, intent)
        if not result:
            return "", [], "none", False
        return result.text, result.evidence, result.source_type, result.structured

    def _retrieve_answer(self, db: Session, bot_profile_id: object, text: str, intent: str) -> tuple[str, list[str], str, bool]:
        result = self._retrieve_answer_result(db, bot_profile_id, text, intent)
        if not result:
            return "", [], "none", False
        return result.text, result.evidence, result.source_type, result.structured

    def _build_answer_result(self, db: Session, conversation: Conversation, text: str, intent: str) -> RetrievedKnowledge | None:
        return self._retrieve_answer_result(db, conversation.bot_profile_id, text, intent)

    def _retrieve_answer_result(self, db: Session, bot_profile_id: object, text: str, intent: str) -> RetrievedKnowledge | None:
        if intent == "faq":
            return self.knowledge.retrieve_faq(db, bot_profile_id, text)
        return self.knowledge.retrieve_knowledge_page(db, bot_profile_id, text)

    def _record_business_reply_candidate(
        self,
        db: Session,
        bot_profile: BotProfile,
        conversation: Conversation | None,
        telegram_chat_id: str,
        telegram_user_id: str,
        display_name: str | None,
        business_connection_id: str,
        text: str,
        raw_payload: dict,
        telegram_message_id: str | None,
        answer_result: RetrievedKnowledge,
    ) -> tuple[Conversation | None, PipelineResult]:
        if answer_result.risk_level == RiskLevel.HIGH:
            return None, self._ignored_business_result("high_risk_knowledge", "high")
        if conversation is None:
            conversation = self.conversations.get_or_create_conversation(
                db=db,
                bot_profile=bot_profile,
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                display_name=display_name,
                telegram_business_connection_id=business_connection_id,
            )
        self.conversations.record_message(
            db,
            conversation=conversation,
            source=MessageSource.CUSTOMER,
            channel=MessageChannel.TELEGRAM_DM,
            content_text=text,
            raw_payload_json=raw_payload,
            telegram_message_id=telegram_message_id,
        )
        is_knowledge_reply = answer_result.source_type == "knowledge_page"
        is_email_reply = answer_result.source_type == "email_auto_reply"
        return conversation, PipelineResult(
            action="knowledge_reply" if is_knowledge_reply else "template_reply",
            text=answer_result.text,
            evidence=answer_result.evidence,
            risk_level=answer_result.risk_level.value,
            intent="email_capture" if is_email_reply else "knowledge" if is_knowledge_reply else "faq",
            source_type=answer_result.source_type,
            structured=answer_result.structured,
            image_assets=answer_result.image_assets,
        )

    @staticmethod
    def _ignored_business_result(intent: str, risk_level: str) -> PipelineResult:
        return PipelineResult(
            action="ignored",
            text="",
            evidence=[],
            risk_level=risk_level,
            intent=intent,
            source_type="business_ignored",
        )

    @staticmethod
    def _unanswered_fallback_message(bot_profile: object) -> str:
        configured = str(getattr(bot_profile, "unanswered_fallback_message", "") or "").strip()
        return configured or DEFAULT_UNANSWERED_FALLBACK_MESSAGE

    @staticmethod
    def _email_auto_reply_message(bot_profile: object) -> str:
        configured = str(getattr(bot_profile, "email_auto_reply_message", "") or "").strip()
        return configured or DEFAULT_EMAIL_AUTO_REPLY_MESSAGE

    def _build_followup_answer(self, db: Session, conversation: Conversation, text: str) -> tuple[str, list[str], str, bool]:
        result = self._build_followup_result(db, conversation, text)
        if not result:
            return "", [], "none", False
        return result.text, result.evidence, result.source_type, result.structured

    def _build_followup_result(self, db: Session, conversation: Conversation, text: str) -> RetrievedKnowledge | None:
        if db is None or not self._looks_like_followup(text):
            return None

        recent_messages = self._get_recent_messages(db, conversation)
        latest_bot_message = next((message for message in recent_messages if message.source == MessageSource.BOT), None)
        previous_customer_message = self._find_previous_customer_message(recent_messages, latest_bot_message)
        if not latest_bot_message or not previous_customer_message:
            return None

        combined_queries = self._build_followup_queries(previous_customer_message.content_text, latest_bot_message.content_text, text)
        if not combined_queries:
            return None

        if latest_bot_message.intent == "faq":
            for query in combined_queries:
                result = self.knowledge.retrieve_faq(db, conversation.bot_profile_id, query)
                if result and not self._is_same_reply(result.text, latest_bot_message.content_text):
                    return result

        for query in combined_queries:
            result = self.knowledge.retrieve_knowledge_page(db, conversation.bot_profile_id, query)
            if result and not self._is_same_reply(result.text, latest_bot_message.content_text):
                return result

        return None

    def _get_recent_messages(self, db: Session, conversation: Conversation, limit: int = 6) -> list[Message]:
        return list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.desc())
                .limit(limit)
            ).all()
        )

    @staticmethod
    def _find_previous_customer_message(recent_messages: list[Message], latest_bot_message: Message | None) -> Message | None:
        if latest_bot_message is None:
            return None

        bot_seen = False
        for message in recent_messages:
            if message.id == latest_bot_message.id:
                bot_seen = True
                continue
            if bot_seen and message.source == MessageSource.CUSTOMER:
                return message
        return None

    @staticmethod
    def _build_followup_queries(previous_customer_text: str, latest_bot_text: str, current_text: str) -> list[str]:
        queries: list[str] = []
        for base in (previous_customer_text, latest_bot_text):
            combined = " ".join(part.strip() for part in [base, current_text] if part and part.strip())
            if combined and combined not in queries:
                queries.append(combined)
        return queries

    @staticmethod
    def _is_same_reply(left: str, right: str) -> bool:
        normalize = lambda value: re.sub(r"\s+", "", value or "")
        return bool(left and right and normalize(left) == normalize(right))

    @staticmethod
    def _looks_like_followup(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if len(stripped) <= 24 and FOLLOWUP_QUANTITY_PATTERN.search(stripped):
            return True
        return len(stripped) <= 16 and any(word in stripped for word in FOLLOWUP_HINT_WORDS)
