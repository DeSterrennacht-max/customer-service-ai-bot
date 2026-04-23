from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.app.db.models.entities import StyleProfile
from backend.api.app.db.session import get_db
from backend.api.app.dependencies import get_accessible_bot_profile, get_current_user, is_super_admin
from backend.api.app.schemas.content import StyleProfileResponse, StyleProfileUpdate
from backend.api.app.services.audit_service import AuditService

router = APIRouter(prefix="/admin/style-profile", tags=["style-profile"])
audit_service = AuditService()


@router.get("", response_model=StyleProfileResponse)
def get_style_profile(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
    bot_profile_id: str | None = None,
) -> StyleProfile:
    statement = select(StyleProfile)
    if bot_profile_id:
        bot_profile = get_accessible_bot_profile(db, user, UUID(bot_profile_id))
        statement = statement.where(StyleProfile.bot_profile_id == bot_profile.id)
    elif not is_super_admin(user):
        statement = statement.where(StyleProfile.tenant_id == user.tenant_id)
    profile = db.scalar(statement.order_by(StyleProfile.created_at.asc()))
    if not profile:
        raise HTTPException(status_code=404, detail="Style profile not found")
    return profile


@router.patch("", response_model=StyleProfileResponse)
def update_style_profile(
    payload: StyleProfileUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
    bot_profile_id: str | None = None,
) -> StyleProfile:
    statement = select(StyleProfile)
    if bot_profile_id:
        bot_profile = get_accessible_bot_profile(db, user, UUID(bot_profile_id))
        statement = statement.where(StyleProfile.bot_profile_id == bot_profile.id)
    elif not is_super_admin(user):
        statement = statement.where(StyleProfile.tenant_id == user.tenant_id)
    profile = db.scalar(statement.order_by(StyleProfile.created_at.asc()))
    if not profile:
        raise HTTPException(status_code=404, detail="Style profile not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    audit_service.record(
        db=db,
        tenant_id=str(profile.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="style_profile.updated",
        target_type="style_profile",
        target_id=str(profile.id),
        detail_json=payload.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(profile)
    return profile
