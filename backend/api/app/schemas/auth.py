from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr

from backend.api.app.db.models.entities import UserRole


class LoginRequest(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    id: UUID
    login_username: str
    email: EmailStr | None = None
    role: UserRole
    tenant_id: UUID | None = None
    tenant_name: str | None = None
