"""add content image assets

Revision ID: 20260426_0009
Revises: 20260425_0008
Create Date: 2026-04-26 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260426_0009"
down_revision = "20260425_0008"
branch_labels = None
depends_on = None

EMPTY_LIST = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.add_column(
        "faq_entries",
        sa.Column(
            "image_assets_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=EMPTY_LIST,
        ),
    )
    op.add_column(
        "knowledge_pages",
        sa.Column(
            "image_assets_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=EMPTY_LIST,
        ),
    )
    op.alter_column("faq_entries", "image_assets_json", server_default=None)
    op.alter_column("knowledge_pages", "image_assets_json", server_default=None)


def downgrade() -> None:
    op.drop_column("knowledge_pages", "image_assets_json")
    op.drop_column("faq_entries", "image_assets_json")
