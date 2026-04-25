from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.app.core.defaults import DEFAULT_BOT_WELCOME_MESSAGE
from backend.api.app.db.models.entities import Conversation, ConversationStatus, DeliveryStatus, Message, MessageChannel, MessageSource, RiskLevel, StyleProfile
from backend.api.app.llm.generator_client import GeneratorLLMClient
from backend.api.app.services.audit_service import AuditService
from backend.api.app.services.conversation_service import ConversationService
from backend.api.app.services.handoff_service import HandoffService
from backend.api.app.services.knowledge_service import KnowledgeService
from backend.api.app.services.rule_router import RuleRouteResult, RuleRouter
from backend.api.app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)

CHINESE_NUMBER_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
FOLLOWUP_QUANTITY_PATTERN = re.compile(r"(\d+|[一二两三四五六七八九十])\s*(个|位|席|坐席|人|账号|用户|台)?")
FOLLOWUP_HINT_WORDS = ("这个", "那个", "这样", "这种", "那种", "继续", "然后", "上面", "刚才")
PRICE_CONTEXT_WORDS = ("价格", "价钱", "多少钱", "收费", "费用", "套餐", "坐席", "标准版", "高级版")
PRICING_FACT_QUERIES = ("标准版多少钱", "高级版多少钱", "套餐价格分别是多少", "标准版价格", "高级版价格")
UNANSWERED_HANDOFF_NOTICE = "已为你转接人工客服，请稍等，客服会尽快回复你。"


@dataclass(slots=True)
class PipelineResult:
    action: str
    text: str
    evidence: list[str]
    risk_level: str
    intent: str
    source_type: str = "none"
    structured: bool = False


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

        followup_first = self._looks_like_followup(text)
        if followup_first:
            answer, evidence, source_type, structured = self._build_followup_answer(db, conversation, text)
            if answer:
                return PipelineResult(
                    action="knowledge_reply" if source_type == "knowledge_page" else "template_reply",
                    text=answer,
                    evidence=evidence,
                    risk_level="low",
                    intent="knowledge" if source_type == "knowledge_page" else "faq",
                    source_type=source_type,
                    structured=structured,
                )

        answer, evidence, source_type, structured = self._build_answer(db, conversation, text, "faq")
        if answer:
            return PipelineResult(
                action="template_reply",
                text=answer,
                evidence=evidence,
                risk_level="low",
                intent="faq",
                source_type=source_type,
                structured=structured,
            )

        if not followup_first:
            answer, evidence, source_type, structured = self._build_followup_answer(db, conversation, text)
            if answer:
                return PipelineResult(
                    action="knowledge_reply" if source_type == "knowledge_page" else "template_reply",
                    text=answer,
                    evidence=evidence,
                    risk_level="low",
                    intent="knowledge" if source_type == "knowledge_page" else "faq",
                    source_type=source_type,
                    structured=structured,
                )

        answer, evidence, source_type, structured = self._build_answer(db, conversation, text, "knowledge")
        if answer:
            return PipelineResult(
                action="knowledge_reply",
                text=answer,
                evidence=evidence,
                risk_level="low",
                intent="knowledge",
                source_type=source_type,
                structured=structured,
            )

        return self._handoff(
            db,
            conversation,
            text,
            RuleRouteResult(action="handoff", intent="unanswered", risk_level="medium"),
            customer_notice=UNANSWERED_HANDOFF_NOTICE,
        )

    def dispatch_reply(self, db: Session, conversation: Conversation, pipeline_result: PipelineResult) -> str | None:
        if pipeline_result.action == "handoff" and not pipeline_result.text:
            return None

        style = db.query(StyleProfile).filter(StyleProfile.bot_profile_id == conversation.bot_profile_id).first()
        humanized = pipeline_result.text
        bot_profile = self.conversations.get_bot_profile(db, conversation.bot_profile_id) or self.conversations.get_default_bot_profile(db)
        business_connection_id = getattr(conversation, "telegram_business_connection_id", None)
        if style and pipeline_result.action != "handoff":
            try:
                if pipeline_result.structured and pipeline_result.source_type == "knowledge_page":
                    humanized = self.generator.preserve_structure(
                        text=pipeline_result.text,
                        banned_phrases=style.banned_phrases_json or [],
                    ).text
                else:
                    humanized = self.generator.humanize(
                        fact_answer=pipeline_result.text,
                        tone=style.tone,
                        banned_phrases=style.banned_phrases_json or [],
                    ).text
            except Exception:
                logger.warning("Generator LLM failed; sending original response text", exc_info=True)
                humanized = pipeline_result.text
            if style.typing_enabled:
                if business_connection_id:
                    self.telegram.send_chat_action_sync(
                        bot_profile.telegram_bot_token,
                        conversation.telegram_chat_id,
                        business_connection_id=business_connection_id,
                    )
                else:
                    self.telegram.send_chat_action_sync(bot_profile.telegram_bot_token, conversation.telegram_chat_id)
                delay = random.randint(style.delay_min_ms, style.delay_max_ms) / 1000
                time.sleep(delay)

        if business_connection_id:
            telegram_message_id = self.telegram.send_text_sync(
                bot_profile.telegram_bot_token,
                conversation.telegram_chat_id,
                humanized,
                business_connection_id=business_connection_id,
            )
        else:
            telegram_message_id = self.telegram.send_text_sync(bot_profile.telegram_bot_token, conversation.telegram_chat_id, humanized)
        message = self.conversations.record_message(
            db,
            conversation=conversation,
            source=MessageSource.BOT,
            channel=MessageChannel.TELEGRAM_DM,
            content_text=humanized,
            raw_payload_json={
                "evidence": pipeline_result.evidence,
                "source_type": pipeline_result.source_type,
                "business_connection_id": business_connection_id,
            },
            telegram_message_id=str(telegram_message_id) if telegram_message_id else None,
            intent=pipeline_result.intent,
            risk_level=RiskLevel(pipeline_result.risk_level),
        )
        message.delivery_status = DeliveryStatus.SENT if telegram_message_id else DeliveryStatus.FAILED
        self.audit.record(
            db=db,
            tenant_id=str(conversation.tenant_id),
            actor_type="system",
            action="message.dispatched",
            target_type="conversation",
            target_id=str(conversation.id),
            detail_json={
                "action": pipeline_result.action,
                "intent": pipeline_result.intent,
                "risk_level": pipeline_result.risk_level,
                "source_type": pipeline_result.source_type,
                "evidence": pipeline_result.evidence,
                "sent": bool(telegram_message_id),
                "business_connection_id": business_connection_id,
            },
        )
        return humanized

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
        if intent == "faq":
            result = self.knowledge.retrieve_faq(db, conversation.bot_profile_id, text)
        else:
            result = self.knowledge.retrieve_knowledge_page(db, conversation.bot_profile_id, text)

        if not result:
            return "", [], "none", False
        return result.text, result.evidence, result.source_type, result.structured

    def _build_followup_answer(self, db: Session, conversation: Conversation, text: str) -> tuple[str, list[str], str, bool]:
        if db is None or not self._looks_like_followup(text):
            return "", [], "none", False

        recent_messages = self._get_recent_messages(db, conversation)
        latest_bot_message = next((message for message in recent_messages if message.source == MessageSource.BOT), None)
        previous_customer_message = self._find_previous_customer_message(recent_messages, latest_bot_message)
        if not latest_bot_message or not previous_customer_message:
            return "", [], "none", False

        combined_queries = self._build_followup_queries(previous_customer_message.content_text, latest_bot_message.content_text, text)
        if not combined_queries:
            return "", [], "none", False

        price_answer = self._build_quantity_price_answer(
            db=db,
            conversation=conversation,
            current_text=text,
            previous_customer_text=previous_customer_message.content_text,
            latest_bot_text=latest_bot_message.content_text,
        )
        if price_answer:
            return price_answer

        if latest_bot_message.intent == "faq":
            for query in combined_queries:
                result = self.knowledge.retrieve_faq(db, conversation.bot_profile_id, query)
                if result and not self._is_same_reply(result.text, latest_bot_message.content_text):
                    return result.text, result.evidence, result.source_type, result.structured

        for query in combined_queries:
            result = self.knowledge.retrieve_knowledge_page(db, conversation.bot_profile_id, query)
            if result and not self._is_same_reply(result.text, latest_bot_message.content_text):
                return result.text, result.evidence, result.source_type, result.structured

        return "", [], "none", False

    def _build_quantity_price_answer(
        self,
        db: Session,
        conversation: Conversation,
        current_text: str,
        previous_customer_text: str,
        latest_bot_text: str,
    ) -> tuple[str, list[str], str, bool] | None:
        quantity = self._extract_quantity(current_text)
        if not quantity or not self._has_price_context(previous_customer_text, latest_bot_text):
            return None

        fact_queries = [
            *self._build_followup_queries(previous_customer_text, latest_bot_text, current_text),
            *PRICING_FACT_QUERIES,
        ]
        seen_queries: set[str] = set()
        for query in fact_queries:
            if query in seen_queries:
                continue
            seen_queries.add(query)
            result = self.knowledge.retrieve_faq(db, conversation.bot_profile_id, query)
            if not result:
                continue
            tiers = self._parse_per_seat_pricing(result.text)
            if not tiers:
                continue
            reply = self._render_quantity_price_reply(quantity, tiers)
            return reply, [*result.evidence, "system:quantity_price_quote"], result.source_type, False
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
    def _extract_quantity(text: str) -> int | None:
        match = FOLLOWUP_QUANTITY_PATTERN.search(text.strip())
        if not match:
            return None
        raw_quantity = match.group(1)
        quantity = int(raw_quantity) if raw_quantity.isdigit() else CHINESE_NUMBER_MAP.get(raw_quantity, 0)
        return quantity if quantity > 0 else None

    @staticmethod
    def _has_price_context(*texts: str) -> bool:
        combined = " ".join(texts)
        return any(word in combined for word in PRICE_CONTEXT_WORDS)

    @staticmethod
    def _is_same_reply(left: str, right: str) -> bool:
        normalize = lambda value: re.sub(r"\s+", "", value or "")
        return bool(left and right and normalize(left) == normalize(right))

    @staticmethod
    def _parse_per_seat_pricing(text: str) -> list[dict[str, object]]:
        tiers: list[dict[str, object]] = []
        for name in ("标准版", "高级版"):
            segment_match = re.search(fr"{name}[^。；;\n]*", text)
            if not segment_match:
                continue
            segment = segment_match.group(0)
            seat_price_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|USDT)?\s*/\s*坐席\s*/\s*年", segment)
            if not seat_price_match:
                continue
            promo_match = re.search(r"优惠价\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+|元)?", segment)
            tiers.append(
                {
                    "name": name,
                    "seat_price": float(seat_price_match.group(1)),
                    "seat_currency": "元",
                    "promo_price": float(promo_match.group(1)) if promo_match else None,
                    "promo_currency": promo_match.group(2) if promo_match and promo_match.group(2) else "USDT",
                }
            )
        return tiers

    @classmethod
    def _render_quantity_price_reply(cls, quantity: int, tiers: list[dict[str, object]]) -> str:
        lines = [f"按你说的 {quantity} 位坐席，按年费用可以这样算："]
        for tier in tiers:
            seat_price = float(tier["seat_price"])
            total = seat_price * quantity
            line = f"- {tier['name']}：{cls._format_amount(seat_price)}/坐席/年，合计 {cls._format_amount(total)} 元/年"
            promo_price = tier.get("promo_price")
            if promo_price is not None:
                promo_total = float(promo_price) * quantity
                line += f"；优惠价合计 {cls._format_amount(promo_total)} {tier['promo_currency']}"
            lines.append(line)
        lines.append("如果你还没确定版本，可以先告诉我你需要标准版还是高级版，我再按对应版本继续确认。")
        return "\n".join(lines)

    @staticmethod
    def _format_amount(value: float) -> str:
        return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _looks_like_followup(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if len(stripped) <= 24 and FOLLOWUP_QUANTITY_PATTERN.search(stripped):
            return True
        return len(stripped) <= 16 and any(word in stripped for word in FOLLOWUP_HINT_WORDS)
