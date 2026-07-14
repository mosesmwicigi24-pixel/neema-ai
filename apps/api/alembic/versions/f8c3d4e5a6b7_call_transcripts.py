"""calls — recording + transcript + AI summary columns

Revision ID: f8c3d4e5a6b7
Revises: e6a1c2d3f4b5
Create Date: 2026-07-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f8c3d4e5a6b7"
down_revision: Union[str, Sequence[str], None] = "e6a1c2d3f4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS recording_url VARCHAR(500)")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS transcript TEXT")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS transcript_lang VARCHAR(12)")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS summary TEXT")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS transcript_status VARCHAR(20) DEFAULT 'none'")


def downgrade() -> None:
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS transcript_status")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS summary")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS transcript_lang")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS transcript")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS recording_url")
