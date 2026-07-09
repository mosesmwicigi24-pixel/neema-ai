"""add comment_context to messages

Revision ID: c3f7a1b9d2e4
Revises: a1b2c3d4e5f6
Create Date: 2026-07-09

The Message model gained `comment_context` (JSONB) — the source-post card for a
Facebook/Instagram comment conversation — in commit 85f1643, but no migration
ever added the column. So the DEPLOYED model selected `messages.comment_context`
that the prod DB didn't have, 500ing every message query/insert (the inbox list,
thread view, comment capture, agent reply). Health stayed 200 because /api/health
only pings Redis, not the DB.

Idempotent ADD/DROP (`IF [NOT] EXISTS`) so it applies cleanly whether or not the
column somehow already exists.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f7a1b9d2e4"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS comment_context JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS comment_context")
