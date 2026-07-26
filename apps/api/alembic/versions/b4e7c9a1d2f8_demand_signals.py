"""demand_signals — what customers asked for that we couldn't sell

Revision ID: b4e7c9a1d2f8
Revises: a7d9e1f3b5c2
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b4e7c9a1d2f8"
down_revision: Union[str, Sequence[str], None] = "a7d9e1f3b5c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS demand_signals (
            id         UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            query      VARCHAR(200) NOT NULL,
            raw_query  TEXT,
            kind       VARCHAR(20) NOT NULL DEFAULT 'no_match',
            channel    VARCHAR(20),
            person_id  UUID REFERENCES persons(id) ON DELETE SET NULL,
            wa_id      VARCHAR(64),
            detail     TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_demand_created ON demand_signals (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_demand_query ON demand_signals (query)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_demand_kind ON demand_signals (kind)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_demand_wa_id ON demand_signals (wa_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS demand_signals")
