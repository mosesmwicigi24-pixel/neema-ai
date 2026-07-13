"""calls — WhatsApp voice call lifecycle records

Revision ID: e6a1c2d3f4b5
Revises: d5e8f2a3b4c6
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e6a1c2d3f4b5"
down_revision: Union[str, Sequence[str], None] = "d5e8f2a3b4c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id UUID PRIMARY KEY,
            call_id VARCHAR(200) UNIQUE,
            wa_id VARCHAR(30),
            caller_name VARCHAR(200),
            direction VARCHAR(10),
            status VARCHAR(20),
            person_id UUID REFERENCES persons(id) ON DELETE SET NULL,
            agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            duration INTEGER,
            started_at TIMESTAMPTZ,
            answered_at TIMESTAMPTZ,
            ended_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_calls_call_id ON calls (call_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_calls_wa_id ON calls (wa_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_calls_status ON calls (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_calls_started_at ON calls (started_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS calls")
