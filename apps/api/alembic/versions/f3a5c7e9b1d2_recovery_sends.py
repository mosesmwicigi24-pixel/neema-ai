"""recovery_sends — one row per message a daily recovery sweep actually sent

Revision ID: f3a5c7e9b1d2
Revises: e4b6d8f0a2c4
Create Date: 2026-10-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f3a5c7e9b1d2"
down_revision: Union[str, Sequence[str], None] = "e4b6d8f0a2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS recovery_sends (
            id              UUID PRIMARY KEY,
            job             VARCHAR(32)  NOT NULL,
            conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
            person_id       UUID REFERENCES persons(id) ON DELETE SET NULL,
            channel         VARCHAR(20)  NOT NULL DEFAULT 'whatsapp',
            ref             VARCHAR(200),
            sent_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_recovery_sends_job_sent_at ON recovery_sends (job, sent_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_recovery_sends_conversation_id ON recovery_sends (conversation_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recovery_sends")
