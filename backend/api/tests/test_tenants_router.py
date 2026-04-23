from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api.app.db.models.entities import UserRole
from backend.api.app.routers import tenants as tenants_router
from backend.api.app.routers.tenants import create_tenant, reset_tenant_admin_password, update_tenant
from backend.api.app.schemas.content import TenantCreate, TenantUpdate


class FakeSession:
    def __init__(self, tenant: object | None, admin: object | None = None) -> None:
        self.tenant = tenant
        self.admin = admin
        self.committed = False
        self.refreshed = False

    def get(self, _model: object, _key: object) -> object | None:
        return self.tenant

    def add(self, tenant: object) -> None:
        if getattr(tenant, "role", None) == UserRole.ADMIN:
            self.admin = tenant
        else:
            self.tenant = tenant

    def flush(self) -> None:
        now = datetime.now(timezone.utc)
        if self.tenant and getattr(self.tenant, "id", None) is None:
            self.tenant.id = uuid4()
            self.tenant.created_at = now
        if self.admin and getattr(self.admin, "id", None) is None:
            self.admin.id = uuid4()
            self.admin.created_at = now

    def commit(self) -> None:
        self.committed = True

    def refresh(self, tenant: object) -> None:
        self.refreshed = True
        self.tenant = tenant


def test_create_tenant_allows_super_admin() -> None:
    db = FakeSession(None)
    user = SimpleNamespace(role=UserRole.SUPER_ADMIN)
    now = datetime.now(timezone.utc)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tenants_router, "get_user_by_login_username", lambda db, login_username: None)
    monkeypatch.setattr(tenants_router, "generate_temporary_password", lambda: "TempPass123")

    response = create_tenant(
        TenantCreate(name="Tenant A", login_username="tenant_a", status="active", valid_from=now, valid_until=None),
        db=db,
        user=user,
    )
    monkeypatch.undo()

    assert response.name == "Tenant A"
    assert response.admin_login_username == "tenant_a"
    assert response.status == "active"
    assert response.valid_from == now
    assert response.temporary_password == "TempPass123"
    assert db.committed is True


def test_update_tenant_allows_super_admin_to_rename() -> None:
    tenant = SimpleNamespace(
        id=uuid4(),
        name="Default Tenant",
        status="active",
        valid_from=None,
        valid_until=None,
        created_at=datetime.now(timezone.utc),
    )
    admin = SimpleNamespace(id=uuid4(), login_username="default_tenant", role=UserRole.ADMIN)
    db = FakeSession(tenant, admin=admin)
    user = SimpleNamespace(role=UserRole.SUPER_ADMIN)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tenants_router, "get_tenant_admin", lambda db, tenant_id: admin)
    monkeypatch.setattr(tenants_router, "get_user_by_login_username", lambda db, login_username: None)

    valid_until = datetime.now(timezone.utc)
    response = update_tenant(
        str(tenant.id),
        TenantUpdate(name="007Chat", login_username="tenant_007", status="inactive", valid_until=valid_until),
        db=db,
        user=user,
    )
    monkeypatch.undo()

    assert response.name == "007Chat"
    assert response.admin_login_username == "tenant_007"
    assert response.status == "inactive"
    assert response.valid_until == valid_until
    assert db.committed is True


def test_update_tenant_rejects_non_super_admin() -> None:
    tenant = SimpleNamespace(
        id=uuid4(),
        name="Default Tenant",
        status="active",
        valid_from=None,
        valid_until=None,
        created_at=datetime.now(timezone.utc),
    )
    db = FakeSession(tenant)
    user = SimpleNamespace(role=UserRole.ADMIN)

    with pytest.raises(HTTPException) as exc_info:
        update_tenant(str(tenant.id), TenantUpdate(name="007Chat", login_username="tenant_007"), db=db, user=user)

    assert exc_info.value.status_code == 403


def test_reset_admin_password_returns_one_time_password() -> None:
    tenant = SimpleNamespace(
        id=uuid4(),
        name="Tenant A",
        status="active",
        valid_from=None,
        valid_until=None,
        created_at=datetime.now(timezone.utc),
    )
    admin = SimpleNamespace(id=uuid4(), login_username="tenant_a", role=UserRole.ADMIN, password_hash="old")
    db = FakeSession(tenant, admin=admin)
    user = SimpleNamespace(role=UserRole.SUPER_ADMIN)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tenants_router, "get_tenant_admin", lambda db, tenant_id: admin)
    monkeypatch.setattr(tenants_router, "generate_temporary_password", lambda: "ResetPass123")

    response = reset_tenant_admin_password(str(tenant.id), db=db, user=user)
    monkeypatch.undo()

    assert response.tenant_id == tenant.id
    assert response.admin_login_username == "tenant_a"
    assert response.temporary_password == "ResetPass123"
    assert db.committed is True
