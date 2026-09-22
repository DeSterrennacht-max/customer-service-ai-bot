from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.api.app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_token(subject: str, expires_delta: timedelta, token_type: str, *, auth_version: int = 1, session_id: str | None = None) -> str:
    settings = get_settings()
    to_encode: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + expires_delta,
        "ver": auth_version,
        "sid": session_id,
        "jti": str(uuid4()),
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, **claims: Any) -> str:
    settings = get_settings()
    return create_token(subject, timedelta(minutes=settings.access_token_expire_minutes), "access", **claims)


def create_refresh_token(subject: str, **claims: Any) -> str:
    settings = get_settings()
    return create_token(subject, timedelta(days=settings.refresh_token_expire_days), "refresh", **claims)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:  # pragma: no cover - thin wrapper
        raise ValueError("Invalid token") from exc


def validate_new_password(password: str) -> None:
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise ValueError("密码须至少 12 个字符，且 UTF-8 编码不超过 72 字节")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise ValueError("密码须同时包含字母和数字")
