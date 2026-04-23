"""expand user role column length

Revision ID: 20260419_0003
Revises: 20260419_0002
Create Date: 2026-04-19 00:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260419_0003"
down_revision = "20260419_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "role", existing_type=sa.String(length=5), type_=sa.String(length=32), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("users", "role", existing_type=sa.String(length=32), type_=sa.String(length=5), existing_nullable=False)
