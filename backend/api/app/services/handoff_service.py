from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.app.db.models.entities import Conversation, ConversationStatus, HandoffStatus, HandoffTicket, Message
from backend.api.app.db.models.entities import MessageChannel, MessageSource, RiskLevel
from backend.api.app.services.audit_service import AuditService
from backend.api.app.services.telegram_service import TelegramService


class HandoffService:
    def __init__(self) -> None:
        self.telegram = TelegramService()
        self.audit = AuditService()

    def create_ticket(self, db: Session, conversation: Conversation, reason: str, summary_text: str) -> HandoffTicket:
        ticket = db.scalar(
            select(HandoffTicket)
            .where(HandoffTicket.conversation_id == conversation.id)
            .order_by(HandoffTicket.created_at.desc())
        )
        if ticket and ticket.status in {HandoffStatus.OPEN, HandoffStatus.ACTIVE}:
            return ticket

        ticket = HandoffTicket(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            group_chat_id=None,
            group_thread_key=None,
            status=HandoffStatus.OPEN,
            reason=reason,
            summary_text=summary_text,
            created_by="system",
        )
        db.add(ticket)
        db.flush()
        conversation.status = ConversationStatus.HANDOFF
        conversation.handoff_ticket_id = ticket.id
        self.audit.record(
            db=db,
            tenant_id=str(conversation.tenant_id),
            actor_type="system",
            action="handoff.created",
            target_type="handoff_ticket",
            target_id=str(ticket.id),
            detail_json={"conversation_id": str(conversation.id), "reason": reason},
        )
        return ticket

    def _extract_username_from_payload(self, payload: dict[str, Any] | None) -> str | None:
        if not payload:
            return None
        message = payload.get("message") or payload.get("edited_message") or {}
        from_user = message.get("from") or {}
        username = from_user.get("username")
        if not username:
            return None
        return str(username).lstrip("@")

    def _customer_label(self, db: Session, conversation: Conversation) -> str:
        latest_customer_message = db.scalar(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.source == MessageSource.CUSTOMER,
            )
            .order_by(Message.created_at.desc())
        )
        if latest_customer_message:
            username = self._extract_username_from_payload(latest_customer_message.raw_payload_json)
            if username:
                return f"@{username}"

        display_name = (conversation.customer_display_name or "").strip()
        if display_name:
            return display_name if display_name.startswith("@") else display_name
        return str(conversation.telegram_user_id)

    def _reason_label(self, reason: str) -> str:
        reason_map = {
            "human_request": "客户触发人工客服介入",
            "complaint": "客户投诉，需人工介入",
            "refund": "客户提及退款，需人工介入",
            "needs_human": "需人工进一步处理",
        }
        return reason_map.get(reason, reason)

    def _build_handoff_summary(self, db: Session, ticket: HandoffTicket, conversation: Conversation) -> str:
        return (
            f"[转人工]\n"
            f"客户: {self._customer_label(db, conversation)}\n"
            f"会话ID: {conversation.id}\n"
            f"原因: {self._reason_label(ticket.reason)}\n\n"
            f"信息内容:\n{ticket.summary_text}"
        )

    def notify_support_group(self, db: Session, ticket: HandoffTicket, conversation: Conversation, bot_token: str, group_chat_id: str | None) -> HandoffTicket:
        if not group_chat_id:
            return ticket

        summary = self._build_handoff_summary(db, ticket, conversation)
        message_id = self.telegram.send_text_sync(bot_token, group_chat_id, summary)
        if message_id:
            ticket.group_chat_id = group_chat_id
            ticket.group_thread_key = str(message_id)
            ticket.status = HandoffStatus.ACTIVE
            db.add(
                Message(
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    source=MessageSource.SYSTEM,
                    channel=MessageChannel.TELEGRAM_GROUP,
                    telegram_message_id=str(message_id),
                    content_text=summary,
                    raw_payload_json={
                        "handoff_ticket_id": str(ticket.id),
                        "handoff_group_message_type": "summary",
                        "group_chat_id": group_chat_id,
                    },
                    risk_level=RiskLevel.HIGH,
                )
            )
        return ticket

    def _find_ticket_for_group_reply(self, db: Session, group_chat_id: str, reply_to_message_id: str) -> HandoffTicket | None:
        candidate_messages = list(
            db.scalars(
                select(Message).where(
                    Message.channel == MessageChannel.TELEGRAM_GROUP,
                    Message.source == MessageSource.SYSTEM,
                    Message.telegram_message_id == reply_to_message_id,
                )
            ).all()
        )
        for message in candidate_messages:
            payload = message.raw_payload_json or {}
            handoff_ticket_id = payload.get("handoff_ticket_id")
            if not handoff_ticket_id:
                continue
            try:
                ticket = db.get(HandoffTicket, UUID(str(handoff_ticket_id)))
            except (ValueError, TypeError):
                continue
            if not ticket:
                continue
            if ticket.group_chat_id != group_chat_id:
                continue
            if ticket.status not in {HandoffStatus.OPEN, HandoffStatus.ACTIVE}:
                continue
            return ticket

        return db.scalar(
            select(HandoffTicket).where(
                HandoffTicket.group_chat_id == group_chat_id,
                HandoffTicket.group_thread_key == reply_to_message_id,
                HandoffTicket.status.in_([HandoffStatus.OPEN, HandoffStatus.ACTIVE]),
            )
        )

    def handle_group_reply(
        self,
        db: Session,
        group_chat_id: str,
        incoming_group_message_id: str | None,
        reply_to_message_id: str | None,
        text: str,
        bot_token: str,
    ) -> bool:
        if not reply_to_message_id:
            return False

        ticket = self._find_ticket_for_group_reply(db, group_chat_id, reply_to_message_id)
        if not ticket:
            return False

        conversation = db.get(Conversation, ticket.conversation_id)
        if not conversation:
            return False

        outbound_id = self.telegram.send_text_sync(bot_token, conversation.telegram_chat_id, text)
        db.add(
            Message(
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                source=MessageSource.AGENT,
                channel=MessageChannel.TELEGRAM_GROUP,
                telegram_message_id=incoming_group_message_id,
                reply_to_message_id=reply_to_message_id,
                content_text=text,
                raw_payload_json={
                    "handoff_ticket_id": str(ticket.id),
                    "outbound_customer_message_id": str(outbound_id) if outbound_id else None,
                },
                risk_level=RiskLevel.MEDIUM,
            )
        )
        conversation.last_message_at = datetime.now(timezone.utc)
        self.audit.record(
            db=db,
            tenant_id=str(conversation.tenant_id),
            actor_type="system",
            action="handoff.group_reply_forwarded",
            target_type="conversation",
            target_id=str(conversation.id),
            detail_json={"ticket_id": str(ticket.id)},
        )
        return True

    def sync_customer_message_to_group(self, db: Session, conversation: Conversation, text: str, bot_token: str) -> None:
        if not conversation.handoff_ticket_id:
            return
        ticket = db.get(HandoffTicket, conversation.handoff_ticket_id)
        if not ticket or not ticket.group_chat_id:
            return
        summary = (
            f"[客户继续发送]\n"
            f"客户: {self._customer_label(db, conversation)}\n"
            f"信息内容:\n{text}"
        )
        message_id = self.telegram.send_text_sync(bot_token, ticket.group_chat_id, summary)
        if message_id:
            db.add(
                Message(
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    source=MessageSource.SYSTEM,
                    channel=MessageChannel.TELEGRAM_GROUP,
                    telegram_message_id=str(message_id),
                    content_text=summary,
                    raw_payload_json={
                        "handoff_ticket_id": str(ticket.id),
                        "handoff_group_message_type": "customer_sync",
                        "group_chat_id": ticket.group_chat_id,
                    },
                    risk_level=RiskLevel.HIGH,
                )
            )
        self.audit.record(
            db=db,
            tenant_id=str(conversation.tenant_id),
            actor_type="system",
            action="handoff.customer_message_synced",
            target_type="conversation",
            target_id=str(conversation.id),
            detail_json={"ticket_id": str(ticket.id)},
        )

    def release(self, db: Session, conversation: Conversation) -> Conversation:
        conversation.status = ConversationStatus.OPEN
        if conversation.handoff_ticket_id:
            ticket = db.get(HandoffTicket, conversation.handoff_ticket_id)
            if ticket:
                ticket.status = HandoffStatus.RELEASED
                ticket.released_at = datetime.now(timezone.utc)
                self.audit.record(
                    db=db,
                    tenant_id=str(conversation.tenant_id),
                    actor_type="system",
                    action="handoff.released",
                    target_type="handoff_ticket",
                    target_id=str(ticket.id),
                    detail_json={"conversation_id": str(conversation.id)},
                )
        return conversation

    def release_stale_conversations(
        self,
        db: Session,
        stale_after: timedelta = timedelta(hours=8),
        now: datetime | None = None,
    ) -> list[Conversation]:
        current_time = now or datetime.now(timezone.utc)
        threshold = current_time - stale_after
        released: list[Conversation] = []
        conversations = list(
            db.scalars(
                select(Conversation).where(Conversation.status == ConversationStatus.HANDOFF)
            ).all()
        )
        for conversation in conversations:
            last_customer_message_at = conversation.last_customer_message_at
            if not last_customer_message_at or last_customer_message_at > threshold:
                continue
            self.release(db, conversation)
            released.append(conversation)
        return released
