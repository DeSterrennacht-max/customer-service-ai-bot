"""add telegram business connections

Revision ID: 20260425_0007
Revises: 20260423_0006
Create Date: 2026-04-25 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0007"
down_revision = "20260423_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_business_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("bot_profile_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.String(length=255), nullable=False),
        sa.Column("telegram_user_id", sa.String(length=255), nullable=True),
        sa.Column("telegram_user_chat_id", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("can_reply", sa.Boolean(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rights_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bot_profile_id"], ["bot_profiles.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_profile_id", "connection_id", name="uq_telegram_business_connection_bot_connection"),
    )
    op.create_index(
        "ix_telegram_business_connections_bot_updated",
        "telegram_business_connections",
        ["bot_profile_id", "updated_at"],
    )
    op.create_index(
        "ix_telegram_business_connections_bot_profile_id",
        "telegram_business_connections",
        ["bot_profile_id"],
    )
    op.create_index(
        "ix_telegram_business_connections_tenant_id",
        "telegram_business_connections",
        ["tenant_id"],
    )
    op.add_column("conversations", sa.Column("telegram_business_connection_id", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_conversations_bot_business_chat",
        "conversations",
        ["bot_profile_id", "telegram_business_connection_id", "telegram_chat_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_bot_business_chat", table_name="conversations")
    op.drop_column("conversations", "telegram_business_connection_id")
    op.drop_index("ix_telegram_business_connections_tenant_id", table_name="telegram_business_connections")
    op.drop_index("ix_telegram_business_connections_bot_profile_id", table_name="telegram_business_connections")
    op.drop_index("ix_telegram_business_connections_bot_updated", table_name="telegram_business_connections")
    op.drop_table("telegram_business_connections")
