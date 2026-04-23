from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from backend.api.app.db.models.entities import AuditLog


class AuditService:
    def record(
        self,
        db: Session,
        tenant_id: UUID | str,
        actor_type: str,
        action: str,
        target_type: str,
        actor_id: str | None = None,
        target_id: str | None = None,
        detail_json: dict | None = None,
    ) -> None:
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail_json=detail_json or {},
            )
        )
