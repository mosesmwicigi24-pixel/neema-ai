"""conversations.read_at — when someone last opened the thread

Revision ID: d7f9b1c3e5a7
Revises: c6e8a0b2d4f6
Create Date: 2026-11-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d7f9b1c3e5a7"
down_revision: Union[str, Sequence[str], None] = "c6e8a0b2d4f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS read_at")
