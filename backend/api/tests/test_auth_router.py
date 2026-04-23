from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api.app.core.security import create_access_token, create_refresh_token, decode_token, get_password_hash, verify_password
from backend.api.app.db.models.entities import UserRole
from backend.api.app.routers.auth import change_password, get_me, login, refresh_tokens
from backend.api.app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshTokenRequest


class FakeSession:
    def __init__(self, user: object | None, tenant: object | None = None) -> None:
        self.user = user
        self.tenant = tenant
        self.committed = False

    def scalar(self, _statement: object) -> object | None:
        return self.user

    def get(self, _model: object, _key: object) -> object | None:
        return self.tenant

    def add(self, _obj: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def active_tenant() -> object:
    return SimpleNamespace(status="active", valid_from=None, valid_until=None)


def test_login_accepts_username() -> None:
    user_id = uuid4()
    user = SimpleNamespace(
        id=user_id,
        login_username="default_tenant",
        password_hash=get_password_hash("ChangeMe123!"),
        is_active=True,
        role=UserRole.ADMIN,
        tenant_id=uuid4(),
    )

    response = login(
        LoginRequest(username="default_tenant", password="ChangeMe123!"),
        db=FakeSession(user, tenant=active_tenant()),
    )

    access_payload = decode_token(response.access_token)
    assert access_payload["sub"] == str(user_id)
    assert access_payload["type"] == "access"


def test_refresh_tokens_returns_new_access_and_refresh_tokens() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, is_active=True, role=UserRole.ADMIN, tenant_id=uuid4())

    response = refresh_tokens(
        RefreshTokenRequest(refresh_token=create_refresh_token(str(user_id))),
        db=FakeSession(user, tenant=active_tenant()),
    )

    access_payload = decode_token(response.access_token)
    refresh_payload = decode_token(response.refresh_token)

    assert access_payload["sub"] == str(user_id)
    assert access_payload["type"] == "access"
    assert refresh_payload["sub"] == str(user_id)
    assert refresh_payload["type"] == "refresh"
    assert response.token_type == "bearer"


def test_refresh_tokens_rejects_access_token() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, is_active=True, role=UserRole.ADMIN, tenant_id=uuid4())

    with pytest.raises(HTTPException) as exc_info:
        refresh_tokens(
            RefreshTokenRequest(refresh_token=create_access_token(str(user_id))),
            db=FakeSession(user, tenant=active_tenant()),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token type"


def test_refresh_tokens_rejects_inactive_tenant() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, is_active=True, role=UserRole.ADMIN, tenant_id=uuid4())
    tenant = SimpleNamespace(status="inactive", valid_from=None, valid_until=None)

    with pytest.raises(HTTPException) as exc_info:
        refresh_tokens(
            RefreshTokenRequest(refresh_token=create_refresh_token(str(user_id))),
            db=FakeSession(user, tenant=tenant),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Tenant is not active (inactive)"


def test_get_me_returns_current_user_shape() -> None:
    user_id = uuid4()
    user = SimpleNamespace(
        id=user_id,
        login_username="superadmin",
        email="superadmin@example.com",
        role=UserRole.SUPER_ADMIN,
        tenant_id=None,
    )

    response = get_me(user, db=FakeSession(user, tenant=None))

    assert response.id == user_id
    assert response.login_username == "superadmin"
    assert response.email == "superadmin@example.com"
    assert response.role == UserRole.SUPER_ADMIN
    assert response.tenant_id is None
    assert response.tenant_name is None


def test_get_me_returns_tenant_name_for_admin() -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    user = SimpleNamespace(
        id=user_id,
        login_username="ningmeng",
        email="admin@example.com",
        role=UserRole.ADMIN,
        tenant_id=tenant_id,
    )
    tenant = SimpleNamespace(id=tenant_id, name="ningmeng")

    response = get_me(user, db=FakeSession(user, tenant=tenant))

    assert response.id == user_id
    assert response.login_username == "ningmeng"
    assert response.tenant_id == tenant_id
    assert response.tenant_name == "ningmeng"


def test_change_password_updates_hash() -> None:
    user = SimpleNamespace(
        id=uuid4(),
        login_username="ningmeng",
        password_hash=get_password_hash("OldPass123"),
        is_active=True,
        role=UserRole.ADMIN,
        tenant_id=uuid4(),
    )
    db = FakeSession(user, tenant=active_tenant())

    change_password(
        ChangePasswordRequest(current_password="OldPass123", new_password="NewPass456"),
        user=user,
        db=db,
    )

    assert db.committed is True
    assert verify_password("NewPass456", user.password_hash) is True


def test_change_password_rejects_wrong_current_password() -> None:
    user = SimpleNamespace(
        id=uuid4(),
        login_username="ningmeng",
        password_hash=get_password_hash("OldPass123"),
        is_active=True,
        role=UserRole.ADMIN,
        tenant_id=uuid4(),
    )
    db = FakeSession(user, tenant=active_tenant())

    with pytest.raises(HTTPException) as exc_info:
        change_password(
            ChangePasswordRequest(current_password="WrongPass", new_password="NewPass456"),
            user=user,
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Current password is incorrect"
