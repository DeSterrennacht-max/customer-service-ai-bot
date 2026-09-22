from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.api.app.core.security import verify_password
from backend.api.app.db.models.entities import Tenant, User
from backend.api.app.dependencies import ensure_user_operational, get_current_user
from backend.api.app.db.session import get_db
from backend.api.app.schemas.auth import ChangePasswordRequest, CurrentUserResponse, LoginRequest, RefreshTokenRequest, TokenResponse
from backend.api.app.core.security import get_password_hash, validate_new_password
from backend.api.app.services.auth_session_service import check_login_rate, issue_session_tokens, parse_session_claims, require_current_refresh, revoke_all_sessions, validate_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    identifier = (payload.username or payload.email or "").strip()
    if not identifier:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")

    user = db.scalar(select(User).where(or_(User.login_username == identifier, User.email == identifier)))
    check_login_rate(db, str(user.id) if user else identifier.casefold())
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    ensure_user_operational(user, db)
    # Password resets and refreshes serialize on the user row.
    db.refresh(user, with_for_update=True)
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    tokens = issue_session_tokens(db, user)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(payload: RefreshTokenRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    token_payload = parse_session_claims(payload.refresh_token, "refresh")
    user = db.scalar(select(User).where(User.id == token_payload["user_id"]).with_for_update())
    session = validate_session(db, user, token_payload, lock=True)
    require_current_refresh(session, payload.refresh_token)
    ensure_user_operational(user, db)

    tokens = issue_session_tokens(db, user, session)
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshTokenRequest, db: Annotated[Session, Depends(get_db)]) -> None:
    from datetime import datetime, timezone
    claims = parse_session_claims(payload.refresh_token, "refresh")
    user = db.scalar(select(User).where(User.id == claims["user_id"]).with_for_update())
    session = validate_session(db, user, claims, lock=True)
    require_current_refresh(session, payload.refresh_token)
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()


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
    db.refresh(user, with_for_update=True)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    try:
        validate_new_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")

    user.password_hash = get_password_hash(payload.new_password)
    revoke_all_sessions(db, user)
    db.add(user)
    db.commit()
