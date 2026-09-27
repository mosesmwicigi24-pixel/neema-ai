"""calls — structured post-call insights + follow-up done

Revision ID: c4a7e2b9d1f3
Revises: d7f4b9c2e1a8
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c4a7e2b9d1f3"
down_revision: Union[str, Sequence[str], None] = "d7f4b9c2e1a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS insights JSONB")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS follow_up_done_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS follow_up_done_at")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS insights")
