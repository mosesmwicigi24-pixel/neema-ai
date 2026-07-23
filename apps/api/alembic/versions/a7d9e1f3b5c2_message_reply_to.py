"""messages — reply-to (quote) columns

Revision ID: a7d9e1f3b5c2
Revises: f8c3d4e5a6b7
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a7d9e1f3b5c2"
down_revision: Union[str, Sequence[str], None] = "f8c3d4e5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_id UUID REFERENCES messages(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_text TEXT")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_sender VARCHAR(20)")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS reply_to_sender")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS reply_to_text")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS reply_to_id")
