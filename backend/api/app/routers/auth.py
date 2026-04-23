from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.api.app.core.security import create_access_token, create_refresh_token, decode_token, verify_password
from backend.api.app.db.models.entities import Tenant, User
from backend.api.app.dependencies import ensure_user_operational, get_current_user
from backend.api.app.db.session import get_db
from backend.api.app.schemas.auth import ChangePasswordRequest, CurrentUserResponse, LoginRequest, RefreshTokenRequest, TokenResponse
from backend.api.app.core.security import get_password_hash

router = APIRouter(prefix="/auth", tags=["auth"])


def issue_tokens(user_id: str) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    identifier = (payload.username or payload.email or "").strip()
    if not identifier:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")

    user = db.scalar(select(User).where(or_(User.login_username == identifier, User.email == identifier)))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    ensure_user_operational(user, db)
    return issue_tokens(str(user.id))


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(payload: RefreshTokenRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    try:
        token_payload = decode_token(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if token_payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user = db.scalar(select(User).where(User.id == UUID(token_payload["sub"])))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    ensure_user_operational(user, db)

    return issue_tokens(str(user.id))


@router.get("/me", response_model=CurrentUserResponse)
def get_me(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CurrentUserResponse:
    tenant_name = None
    if user.tenant_id:
        tenant = db.get(Tenant, user.tenant_id)
        tenant_name = tenant.name if tenant else None

    return CurrentUserResponse(
        id=user.id,
        login_username=user.login_username,
        email=user.email,
        role=user.role,
        tenant_id=user.tenant_id,
        tenant_name=tenant_name,
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if not payload.new_password.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password cannot be empty")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")

    user.password_hash = get_password_hash(payload.new_password)
    db.add(user)
    db.commit()
