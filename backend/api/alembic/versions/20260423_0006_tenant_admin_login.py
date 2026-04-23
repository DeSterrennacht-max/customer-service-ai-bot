"""add tenant admin login username

Revision ID: 20260423_0006
Revises: 20260421_0005
Create Date: 2026-04-23 00:00:00.000000
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "20260423_0006"
down_revision = "20260421_0005"
branch_labels = None
depends_on = None


users_table = sa.table(
    "users",
    sa.column("id", sa.String()),
    sa.column("tenant_id", sa.String()),
    sa.column("email", sa.String()),
    sa.column("role", sa.String()),
    sa.column("login_username", sa.String()),
)

tenants_table = sa.table(
    "tenants",
    sa.column("id", sa.String()),
    sa.column("name", sa.String()),
)


def slugify_login_username(value: str, fallback: str = "tenant_admin") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or fallback


def build_login_username(role: str | None, email: str | None, tenant_name: str | None, used: set[str], user_id: str) -> str:
    normalized_role = (role or "").lower()
    if normalized_role == "super_admin":
        base = "superadmin"
    elif tenant_name:
        base = slugify_login_username(tenant_name)
    elif email:
        base = slugify_login_username(email.split("@", 1)[0], fallback="tenant_admin")
    else:
        base = "tenant_admin"

    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def upgrade() -> None:
    op.add_column("users", sa.Column("login_username", sa.String(length=255), nullable=True))
    op.alter_column("users", "tenant_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=True)

    bind = op.get_bind()
    tenant_rows = {
        str(row.id): row.name
        for row in bind.execute(sa.select(tenants_table.c.id, tenants_table.c.name)).fetchall()
    }
    used: set[str] = set()
    user_rows = bind.execute(
        sa.select(
            users_table.c.id,
            users_table.c.tenant_id,
            users_table.c.email,
            users_table.c.role,
        )
    ).fetchall()

    for row in user_rows:
        login_username = build_login_username(
            row.role,
            row.email,
            tenant_rows.get(str(row.tenant_id)) if row.tenant_id is not None else None,
            used,
            str(row.id),
        )
        values: dict[str, object] = {"login_username": login_username}
        if (row.role or "").lower() == "super_admin":
            values["tenant_id"] = None
        bind.execute(users_table.update().where(users_table.c.id == row.id).values(**values))

    op.alter_column("users", "login_username", existing_type=sa.String(length=255), nullable=False)
    op.create_index("ix_users_login_username", "users", ["login_username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_login_username", table_name="users")
    op.drop_column("users", "login_username")
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("users", "tenant_id", existing_type=sa.UUID(), nullable=False)
