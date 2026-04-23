"""add tenant validity window

Revision ID: 20260421_0005
Revises: 20260421_0004
Create Date: 2026-04-21 00:00:01.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_0005"
down_revision = "20260421_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "valid_until")
    op.drop_column("tenants", "valid_from")
