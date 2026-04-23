from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.app.core.security import decode_token
from backend.api.app.db.models.entities import BotProfile, Tenant, User, UserRole
from backend.api.app.db.session import get_db
from backend.api.app.services.tenant_service import is_tenant_operational, tenant_runtime_label

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user = db.scalar(select(User).where(User.id == UUID(payload["sub"])))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    ensure_user_operational(user, db)
    return user


def is_super_admin(user: User) -> bool:
    return user.role == UserRole.SUPER_ADMIN


def ensure_user_operational(user: User, db: Session) -> None:
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    if is_super_admin(user):
        return
    if not user.tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant is not active")

    tenant = db.get(Tenant, user.tenant_id)
    if not is_tenant_operational(tenant):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Tenant is not active ({tenant_runtime_label(tenant)})",
        )


def ensure_tenant_access(user: User, tenant_id: UUID) -> None:
    if is_super_admin(user):
        return
    if user.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def get_accessible_bot_profile(db: Session, user: User, bot_profile_id: UUID) -> BotProfile:
    bot_profile = db.get(BotProfile, bot_profile_id)
    if not bot_profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot profile not found")
    ensure_tenant_access(user, bot_profile.tenant_id)
    return bot_profile
