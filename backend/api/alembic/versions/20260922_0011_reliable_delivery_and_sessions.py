"""Add durable Telegram delivery and revocable login sessions.

Revision ID: 20260922_0011
Revises: 20260426_0010
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260922_0011"
down_revision = "20260426_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("messages", sa.Column("telegram_chat_id", sa.String(255), nullable=True))
    op.execute("""UPDATE messages AS m SET telegram_chat_id = c.telegram_chat_id
                  FROM conversations AS c WHERE m.conversation_id = c.id AND m.channel = 'TELEGRAM_DM'""")
    op.execute("""UPDATE messages AS m SET telegram_chat_id = h.group_chat_id
                  FROM handoff_tickets AS h
                  WHERE m.channel = 'TELEGRAM_GROUP' AND m.raw_payload_json->>'handoff_ticket_id' = h.id::text""")
    op.create_table("auth_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table("login_throttles",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False))
    op.create_table("telegram_updates",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("bot_profile_id", sa.UUID(), sa.ForeignKey("bot_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("bot_profile_id", "update_id", name="uq_telegram_update_bot_update"))
    op.create_index("ix_telegram_updates_bot_profile_id", "telegram_updates", ["bot_profile_id"])
    op.create_index("ix_telegram_updates_pending", "telegram_updates", ["status", "next_attempt_at", "created_at"])
    op.create_table("outbound_deliveries",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("bot_profile_id", sa.UUID(), sa.ForeignKey("bot_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.UUID(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.String(255), nullable=False),
        sa.Column("business_connection_id", sa.String(255)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("automatic", sa.Boolean(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("telegram_message_id", sa.String(255)),
        sa.Column("last_error", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_outbound_deliveries_bot_profile_id", "outbound_deliveries", ["bot_profile_id"])
    op.create_index("ix_outbound_deliveries_message_id", "outbound_deliveries", ["message_id"])
    op.create_index("ix_outbound_deliveries_pending", "outbound_deliveries", ["status", "next_attempt_at", "created_at"])


def downgrade() -> None:
    # Keep accepted updates and session revocations intact during application rollback.
    # The preceding application version tolerates these additive tables/columns.
    raise RuntimeError("Use application rollback; this migration retains delivery and authentication records")
