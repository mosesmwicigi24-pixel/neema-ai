"""client_crashes — crash reports the Android app sends after it closes unexpectedly

Revision ID: d1f3a5c7e9b2
Revises: c7e9f1a3b5d8
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d1f3a5c7e9b2"
down_revision: Union[str, Sequence[str], None] = "c7e9f1a3b5d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS client_crashes (
            id UUID PRIMARY KEY,
            report_id VARCHAR(64) NOT NULL,
            agent_id VARCHAR(64),
            agent_name VARCHAR(120),
            kind VARCHAR(20) NOT NULL,
            occurred_at VARCHAR(40),
            summary VARCHAR(500) NOT NULL DEFAULT '',
            trace TEXT NOT NULL DEFAULT '',
            thread VARCHAR(120),
            app_version VARCHAR(40) NOT NULL DEFAULT '',
            build VARCHAR(40) NOT NULL DEFAULT '',
            device VARCHAR(120) NOT NULL DEFAULT '',
            sdk INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_client_crashes_report_id ON client_crashes (report_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_client_crashes_created_at ON client_crashes (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_crashes")
