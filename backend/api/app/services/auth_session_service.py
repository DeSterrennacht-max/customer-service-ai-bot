from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import case, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.api.app.core.config import get_settings
from backend.api.app.core.security import create_access_token, create_refresh_token, decode_token
from backend.api.app.db.models.entities import AuthSession, LoginThrottle, User
from backend.api.app.schemas.auth import TokenResponse


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def parse_session_claims(token: str, token_type: str) -> dict:
    try:
        claims = decode_token(token)
        if claims.get("type") != token_type:
            raise HTTPException(status_code=401, detail="Invalid token type")
        claims["user_id"] = UUID(claims["sub"])
        claims["session_id"] = UUID(claims["sid"])
        if type(claims.get("ver")) is not int:
            raise ValueError("Missing session version")
        return claims
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(status_code=401, detail="Session expired; please log in again") from exc


def validate_session(db: Session, user: User | None, claims: dict, *, lock: bool = False) -> AuthSession:
    if not user or not user.is_active or user.auth_version != claims["ver"]:
        raise HTTPException(status_code=401, detail="Session expired; please log in again")
    query = select(AuthSession).where(AuthSession.id == claims["session_id"], AuthSession.user_id == user.id)
    if lock:
        query = query.with_for_update()
    session = db.scalar(query)
    if not session or session.revoked_at or session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired; please log in again")
    return session


def issue_session_tokens(db: Session, user: User, session: AuthSession | None = None) -> TokenResponse:
    now = datetime.now(timezone.utc)
    if session is None:
        session = AuthSession(id=uuid4(), user_id=user.id, created_at=now)
        db.add(session)
    claims = {"auth_version": user.auth_version, "session_id": str(session.id)}
    tokens = TokenResponse(
        access_token=create_access_token(str(user.id), **claims),
        refresh_token=create_refresh_token(str(user.id), **claims),
    )
    session.refresh_token_hash = token_hash(tokens.refresh_token)
    session.expires_at = now + timedelta(days=get_settings().refresh_token_expire_days)
    db.flush()
    return tokens


def require_current_refresh(session: AuthSession, token: str) -> None:
    if not hmac.compare_digest(session.refresh_token_hash, token_hash(token)):
        raise HTTPException(status_code=401, detail="Refresh token has already been used")


def revoke_all_sessions(db: Session, user: User) -> None:
    user.auth_version += 1
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))


def check_login_rate(db: Session, identifier: str) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=settings.login_attempt_window_seconds)
    expired = LoginThrottle.window_start <= cutoff
    statement = insert(LoginThrottle).values(key=token_hash(identifier), attempts=1, window_start=now)
    statement = statement.on_conflict_do_update(index_elements=[LoginThrottle.key], set_={
        "attempts": case((expired, 1), else_=LoginThrottle.attempts + 1),
        "window_start": case((expired, now), else_=LoginThrottle.window_start),
    }).returning(LoginThrottle.attempts)
    attempts = db.scalar(statement)
    # Persist failed attempts even when the endpoint subsequently returns 401.
    db.commit()
    if attempts > settings.login_attempt_limit:
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后重试", headers={"Retry-After": str(settings.login_attempt_window_seconds)})
