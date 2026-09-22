from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.api.app.core.account_utils import generate_temporary_password
from backend.api.app.core.security import get_password_hash
from backend.api.app.services.auth_session_service import revoke_all_sessions
from backend.api.app.db.models.entities import Tenant
from backend.api.app.db.session import get_db
from backend.api.app.dependencies import get_current_user, is_super_admin
from backend.api.app.db.models.entities import User, UserRole
from backend.api.app.schemas.content import (
    TenantAdminPasswordResetResponse,
    TenantCreate,
    TenantCreateResponse,
    TenantResponse,
    TenantUpdate,
)

router = APIRouter(prefix="/admin/tenants", tags=["tenants"])


def get_tenant_admin(db: Session, tenant_id: object) -> User | None:
    return db.scalar(select(User).where(User.tenant_id == tenant_id, User.role == UserRole.ADMIN))


def get_user_by_login_username(db: Session, login_username: str) -> User | None:
    return db.scalar(select(User).where(User.login_username == login_username))


def serialize_tenant(tenant: Tenant, admin_login_username: str | None) -> TenantResponse:
    return TenantResponse(
        id=tenant.id,
        created_at=tenant.created_at,
        name=tenant.name,
        admin_login_username=admin_login_username,
        status=tenant.status,
        valid_from=tenant.valid_from,
        valid_until=tenant.valid_until,
    )


@router.get("", response_model=list[TenantResponse])
def list_tenants(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> list[TenantResponse]:
    statement = (
        select(Tenant, User.login_username)
        .outerjoin(User, and_(User.tenant_id == Tenant.id, User.role == UserRole.ADMIN))
        .order_by(Tenant.created_at.desc())
    )
    if not is_super_admin(user):
        statement = statement.where(Tenant.id == user.tenant_id)
    rows = db.execute(statement).all()
    return [serialize_tenant(tenant, admin_login_username) for tenant, admin_login_username in rows]


@router.post("", response_model=TenantCreateResponse)
def create_tenant(
    payload: TenantCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> TenantCreateResponse:
    if not is_super_admin(user):
        raise HTTPException(status_code=403, detail="Forbidden")

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tenant name cannot be empty")
    login_username = payload.login_username.strip()
    if not login_username:
        raise HTTPException(status_code=400, detail="Login username cannot be empty")
    if get_user_by_login_username(db, login_username):
        raise HTTPException(status_code=409, detail="Login username already exists")

    tenant = Tenant(
        name=name,
        status=payload.status.strip() or "active",
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
    )
    db.add(tenant)
    db.flush()

    temporary_password = generate_temporary_password()
    admin = User(
        tenant_id=tenant.id,
        login_username=login_username,
        email=None,
        password_hash=get_password_hash(temporary_password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(tenant)
    return TenantCreateResponse(
        id=tenant.id,
        created_at=tenant.created_at,
        name=tenant.name,
        admin_login_username=login_username,
        status=tenant.status,
        valid_from=tenant.valid_from,
        valid_until=tenant.valid_until,
        temporary_password=temporary_password,
    )


@router.patch("/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> Tenant:
    if not is_super_admin(user):
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    admin = get_tenant_admin(db, tenant.id)
    if not admin:
        raise HTTPException(status_code=404, detail="Tenant admin not found")

    next_name = payload.name.strip()
    if not next_name:
        raise HTTPException(status_code=400, detail="Tenant name cannot be empty")
    next_login_username = admin.login_username
    if payload.login_username is not None:
        next_login_username = payload.login_username.strip()
        if not next_login_username:
            raise HTTPException(status_code=400, detail="Login username cannot be empty")
        existing_user = get_user_by_login_username(db, next_login_username)
        if existing_user and existing_user.id != admin.id:
            raise HTTPException(status_code=409, detail="Login username already exists")

    tenant.name = next_name
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates:
        tenant.status = (payload.status or "").strip() or "active"
    if "valid_from" in updates:
        tenant.valid_from = payload.valid_from
    if "valid_until" in updates:
        tenant.valid_until = payload.valid_until
    if payload.login_username is not None:
        admin.login_username = next_login_username
    db.add(tenant)
    db.add(admin)
    db.commit()
    db.refresh(tenant)
    return serialize_tenant(tenant, admin.login_username)


@router.post("/{tenant_id}/reset-admin-password", response_model=TenantAdminPasswordResetResponse)
def reset_tenant_admin_password(
    tenant_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> TenantAdminPasswordResetResponse:
    if not is_super_admin(user):
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    admin = get_tenant_admin(db, tenant.id)
    if not admin:
        raise HTTPException(status_code=404, detail="Tenant admin not found")

    db.refresh(admin, with_for_update=True)
    temporary_password = generate_temporary_password()
    admin.password_hash = get_password_hash(temporary_password)
    revoke_all_sessions(db, admin)
    db.add(admin)
    db.commit()

    return TenantAdminPasswordResetResponse(
        tenant_id=tenant.id,
        admin_login_username=admin.login_username,
        temporary_password=temporary_password,
    )
