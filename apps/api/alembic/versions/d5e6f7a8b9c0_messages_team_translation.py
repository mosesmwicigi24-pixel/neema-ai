"""messages.translated_text/_from — the team's reading glass on foreign threads.

Customers write to Bethany House in Bulgarian, French, Spanish, Amharic — and
Neema answers each in their own tongue. Which means the HUMAN following the
thread (the owner's ask, 2026-08-18) often cannot read either side of a live
sales conversation on their own dashboard. These two nullable columns hold a
lazily-computed English rendering of any foreign-language message (both
directions), filled the first time a person opens the thread and cached
forever after. Dashboard-only: nothing that sends, and nothing the agent
reads as history, ever touches these columns.

`ADD COLUMN IF NOT EXISTS` keeps the replay idempotent, matching the index
migration before it.

Revision ID: d5e6f7a8b9c0
Revises: c8d9e0f1a2b3
"""
from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS translated_text TEXT")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS translated_from VARCHAR(24)")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS translated_from")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS translated_text")
