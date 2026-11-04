"""pacing_events — what the conversation budget and bot shield would do

Revision ID: b5d7f9a1c3e5
Revises: a4c6e8f0b2d4
Create Date: 2026-11-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b5d7f9a1c3e5"
down_revision: Union[str, Sequence[str], None] = "a4c6e8f0b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS pacing_events (
            id              UUID PRIMARY KEY,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            channel         VARCHAR(20)  NOT NULL DEFAULT 'whatsapp',
            contact         VARCHAR(128) NOT NULL,
            conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
            decision        VARCHAR(16)  NOT NULL,
            reasons         JSONB,
            turns           INTEGER,
            progress        INTEGER,
            budget          INTEGER,
            bot_score       INTEGER,
            mode            VARCHAR(8)   NOT NULL DEFAULT 'shadow',
            owner_mark      VARCHAR(8),
            owner_note      TEXT,
            marked_by       UUID REFERENCES agents(id) ON DELETE SET NULL,
            marked_at       TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_pacing_events_created_at ON pacing_events (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pacing_events_decision ON pacing_events (decision)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pacing_events_conversation_id ON pacing_events (conversation_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pacing_events")
