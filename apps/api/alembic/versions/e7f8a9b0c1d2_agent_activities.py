"""agent_activities — the per-turn trail of what Neema actually DID.

The Activity Log told the story of the system (pickups, check-ins, deals,
orders, calls) but not of the agent: her searches, cards, albums, cart
changes, captures and bookings lived only in log lines. One row per tool
call makes the whole interaction auditable per customer (owner, 2026-08-19).

Raw SQL with IF NOT EXISTS to keep the replay idempotent, matching the
recent messages migrations.

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
"""
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_activities (
            id UUID PRIMARY KEY,
            conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
            person_id UUID REFERENCES persons(id) ON DELETE SET NULL,
            channel VARCHAR(20) NOT NULL,
            contact VARCHAR(128),
            tool VARCHAR(40) NOT NULL,
            summary TEXT NOT NULL,
            detail TEXT,
            payload JSONB,
            created_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_activities_conversation_id_created_at "
               "ON agent_activities (conversation_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_activities_contact "
               "ON agent_activities (contact)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_activities_created_at "
               "ON agent_activities (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_activities")
