"""add bot unanswered fallback message

Revision ID: 20260425_0008
Revises: 20260425_0007
Create Date: 2026-04-25 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_0008"
down_revision = "20260425_0007"
branch_labels = None
depends_on = None

DEFAULT_UNANSWERED_FALLBACK_MESSAGE = sa.text("'稍等，这会儿有点忙，我马上处理'")


def upgrade() -> None:
    op.add_column(
        "bot_profiles",
        sa.Column(
            "unanswered_fallback_message",
            sa.Text(),
            nullable=False,
            server_default=DEFAULT_UNANSWERED_FALLBACK_MESSAGE,
        ),
    )
    op.alter_column("bot_profiles", "unanswered_fallback_message", server_default=None)


def downgrade() -> None:
    op.drop_column("bot_profiles", "unanswered_fallback_message")
