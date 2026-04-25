from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.app.db.models.entities import BotProfile, TelegramBusinessConnection
from backend.api.app.services.audit_service import AuditService


class TelegramBusinessConnectionService:
    def __init__(self) -> None:
        self.audit = AuditService()

    def upsert_business_connection(
        self,
        db: Session,
        bot_profile: BotProfile,
        payload: dict[str, Any],
    ) -> TelegramBusinessConnection | None:
        connection_id = str(payload.get("id") or "").strip()
        if not connection_id:
            return None

        connection = self.get_connection(db, bot_profile.id, connection_id)
        if not connection:
            connection = TelegramBusinessConnection(
                tenant_id=bot_profile.tenant_id,
                bot_profile_id=bot_profile.id,
                connection_id=connection_id,
            )
            db.add(connection)

        user = payload.get("user") or {}
        rights = payload.get("rights") if isinstance(payload.get("rights"), dict) else None
        connection.telegram_user_id = self._string_or_none(user.get("id"))
        connection.telegram_user_chat_id = self._string_or_none(payload.get("user_chat_id"))
        connection.username = self._string_or_none(user.get("username"))
        connection.first_name = self._string_or_none(user.get("first_name"))
        connection.last_name = self._string_or_none(user.get("last_name"))
        connection.can_reply = self._extract_can_reply(payload)
        connection.is_enabled = payload.get("is_enabled", True) is not False
        connection.connected_at = self._timestamp_to_datetime(payload.get("date"))
        connection.rights_json = rights
        connection.raw_payload_json = payload
        connection.updated_at = datetime.now(timezone.utc)
        db.flush()

        self.audit.record(
            db=db,
            tenant_id=str(bot_profile.tenant_id),
            actor_type="system",
            action="telegram.business_connection.updated",
            target_type="telegram_business_connection",
            target_id=str(connection.id),
            detail_json={
                "bot_profile_id": str(bot_profile.id),
                "connection_id": connection.connection_id,
                "is_enabled": connection.is_enabled,
                "can_reply": connection.can_reply,
            },
        )
        return connection

    def ensure_placeholder_connection(
        self,
        db: Session,
        bot_profile: BotProfile,
        connection_id: str,
    ) -> TelegramBusinessConnection:
        connection = self.get_connection(db, bot_profile.id, connection_id)
        if connection:
            return connection

        connection = TelegramBusinessConnection(
            tenant_id=bot_profile.tenant_id,
            bot_profile_id=bot_profile.id,
            connection_id=connection_id,
            can_reply=False,
            is_enabled=True,
            raw_payload_json={"source": "business_message_without_connection_update"},
        )
        db.add(connection)
        db.flush()
        return connection

    def get_connection(
        self,
        db: Session,
        bot_profile_id: UUID,
        connection_id: str,
    ) -> TelegramBusinessConnection | None:
        return db.scalar(
            select(TelegramBusinessConnection)
            .where(
                TelegramBusinessConnection.bot_profile_id == bot_profile_id,
                TelegramBusinessConnection.connection_id == connection_id,
            )
            .limit(1)
        )

    def latest_for_bot(self, db: Session, bot_profile_id: UUID) -> TelegramBusinessConnection | None:
        return db.scalar(
            select(TelegramBusinessConnection)
            .where(TelegramBusinessConnection.bot_profile_id == bot_profile_id)
            .order_by(TelegramBusinessConnection.updated_at.desc())
            .limit(1)
        )

    @staticmethod
    def connection_status(connection: TelegramBusinessConnection | None) -> str:
        if not connection or not connection.is_enabled:
            return "not_connected"
        if connection.can_reply:
            return "ready"
        return "connected_no_reply"

    @staticmethod
    def can_reply(connection: TelegramBusinessConnection | None) -> bool:
        return bool(connection and connection.is_enabled and connection.can_reply)

    @staticmethod
    def _extract_can_reply(payload: dict[str, Any]) -> bool:
        rights = payload.get("rights")
        if isinstance(rights, dict) and "can_reply" in rights:
            return bool(rights.get("can_reply"))
        if "can_reply" in payload:
            return bool(payload.get("can_reply"))
        return False

    @staticmethod
    def _timestamp_to_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(int(value), timezone.utc)
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
