from __future__ import annotations

from datetime import datetime, timezone

from backend.api.app.db.models.entities import Tenant


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_tenant_operational(tenant: Tenant | None, now: datetime | None = None) -> bool:
    if tenant is None:
        return False

    if tenant.status != "active":
        return False

    current = now or utc_now()
    if tenant.valid_from and current < tenant.valid_from:
        return False
    if tenant.valid_until and current > tenant.valid_until:
        return False

    return True


def tenant_runtime_label(tenant: Tenant | None, now: datetime | None = None) -> str:
    if tenant is None:
        return "missing"
    if tenant.status != "active":
        return "inactive"

    current = now or utc_now()
    if tenant.valid_from and current < tenant.valid_from:
        return "not_started"
    if tenant.valid_until and current > tenant.valid_until:
        return "expired"

    return "active"
