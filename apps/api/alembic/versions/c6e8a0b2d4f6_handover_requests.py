"""handover_requests — asking the colleague who holds a chat to hand it over

Revision ID: c6e8a0b2d4f6
Revises: b5d7f9a1c3e5
Create Date: 2026-11-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c6e8a0b2d4f6"
down_revision: Union[str, Sequence[str], None] = "b5d7f9a1c3e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS handover_requests (
            id              UUID PRIMARY KEY,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            from_agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            holder_agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            status          VARCHAR(12) NOT NULL DEFAULT 'pending',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            answered_at     TIMESTAMPTZ,
            answered_by     UUID REFERENCES agents(id) ON DELETE SET NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_handover_requests_conversation_id ON handover_requests (conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_handover_requests_status ON handover_requests (status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS handover_requests")
