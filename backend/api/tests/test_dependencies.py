from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api.app.db.models.entities import UserRole
from backend.api.app.dependencies import ensure_tenant_access, get_accessible_bot_profile, is_super_admin


class FakeSession:
    def __init__(self, bot_profile: object | None = None) -> None:
        self.bot_profile = bot_profile

    def get(self, _model: object, _key: object) -> object | None:
        return self.bot_profile


def test_is_super_admin_detects_role() -> None:
    super_admin = SimpleNamespace(role=UserRole.SUPER_ADMIN)
    admin = SimpleNamespace(role=UserRole.ADMIN)

    assert is_super_admin(super_admin) is True
    assert is_super_admin(admin) is False


def test_ensure_tenant_access_rejects_cross_tenant_for_admin() -> None:
    user = SimpleNamespace(role=UserRole.ADMIN, tenant_id=uuid4())

    with pytest.raises(HTTPException) as exc_info:
        ensure_tenant_access(user, uuid4())

    assert exc_info.value.status_code == 403


def test_get_accessible_bot_profile_rejects_cross_tenant_bot() -> None:
    user = SimpleNamespace(role=UserRole.ADMIN, tenant_id=uuid4())
    bot_profile = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    db = FakeSession(bot_profile=bot_profile)

    with pytest.raises(HTTPException) as exc_info:
        get_accessible_bot_profile(db, user, bot_profile.id)

    assert exc_info.value.status_code == 403
