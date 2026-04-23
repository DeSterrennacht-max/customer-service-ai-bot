"""add bot welcome message

Revision ID: 20260421_0004
Revises: 20260419_0003
Create Date: 2026-04-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_0004"
down_revision = "20260419_0003"
branch_labels = None
depends_on = None


DEFAULT_WELCOME_MESSAGE = sa.text(
    "'你好，我是客服助手。你可以直接告诉我你想了解价格、套餐、功能，或者把你遇到的问题发给我，我会先帮你处理；如果你需要人工、投诉或退款，也可以直接说。'"
)


def upgrade() -> None:
    op.add_column(
        "bot_profiles",
        sa.Column(
            "welcome_message",
            sa.Text(),
            nullable=False,
            server_default=DEFAULT_WELCOME_MESSAGE,
        ),
    )
    op.alter_column("bot_profiles", "welcome_message", server_default=None)


def downgrade() -> None:
    op.drop_column("bot_profiles", "welcome_message")
