"""parishes — the institution behind the individual

Revision ID: c5f8d2e3a9b1
Revises: b4e7c9a1d2f8
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c5f8d2e3a9b1"
down_revision: Union[str, Sequence[str], None] = "b4e7c9a1d2f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS parishes (
            id         UUID PRIMARY KEY,
            name       VARCHAR(200) NOT NULL,
            norm       VARCHAR(200) NOT NULL UNIQUE,
            location   VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_parishes_norm ON parishes (norm)")
    op.execute("ALTER TABLE persons ADD COLUMN IF NOT EXISTS parish_id UUID REFERENCES parishes(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_persons_parish ON persons (parish_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE persons DROP COLUMN IF EXISTS parish_id")
    op.execute("DROP TABLE IF EXISTS parishes")
