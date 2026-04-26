"""add bot email auto reply

Revision ID: 20260426_0010
Revises: 20260426_0009
Create Date: 2026-04-26 00:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_0010"
down_revision = "20260426_0009"
branch_labels = None
depends_on = None

DEFAULT_EMAIL_AUTO_REPLY_MESSAGE = sa.text("'已收到你的邮箱，我们会根据你提供的信息继续处理。'")


def upgrade() -> None:
    op.add_column(
        "bot_profiles",
        sa.Column("email_auto_reply_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "bot_profiles",
        sa.Column("email_auto_reply_message", sa.Text(), nullable=False, server_default=DEFAULT_EMAIL_AUTO_REPLY_MESSAGE),
    )
    op.alter_column("bot_profiles", "email_auto_reply_enabled", server_default=None)
    op.alter_column("bot_profiles", "email_auto_reply_message", server_default=None)


def downgrade() -> None:
    op.drop_column("bot_profiles", "email_auto_reply_message")
    op.drop_column("bot_profiles", "email_auto_reply_enabled")
