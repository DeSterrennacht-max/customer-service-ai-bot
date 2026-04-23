"""add bot keyword fields

Revision ID: 20260419_0002
Revises: 20260415_0001
Create Date: 2026-04-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260419_0002"
down_revision = "20260415_0001"
branch_labels = None
depends_on = None


FAQ_HINT_KEYWORDS = sa.text("'[\"价格\", \"套餐\", \"试用\", \"功能\", \"支持\"]'::jsonb")
HIGH_RISK_KEYWORDS = sa.text("'[\"人工\", \"投诉\", \"退款\", \"退费\", \"律师\", \"举报\"]'::jsonb")
SENSITIVE_KEYWORDS = sa.text("'[\"骂\", \"骗\", \"垃圾\", \"诈骗\"]'::jsonb")


def upgrade() -> None:
    op.add_column(
        "bot_profiles",
        sa.Column(
            "faq_hint_keywords_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=FAQ_HINT_KEYWORDS,
        ),
    )
    op.add_column(
        "bot_profiles",
        sa.Column(
            "high_risk_keywords_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=HIGH_RISK_KEYWORDS,
        ),
    )
    op.add_column(
        "bot_profiles",
        sa.Column(
            "sensitive_keywords_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=SENSITIVE_KEYWORDS,
        ),
    )

    op.alter_column("bot_profiles", "faq_hint_keywords_json", server_default=None)
    op.alter_column("bot_profiles", "high_risk_keywords_json", server_default=None)
    op.alter_column("bot_profiles", "sensitive_keywords_json", server_default=None)


def downgrade() -> None:
    op.drop_column("bot_profiles", "sensitive_keywords_json")
    op.drop_column("bot_profiles", "high_risk_keywords_json")
    op.drop_column("bot_profiles", "faq_hint_keywords_json")
