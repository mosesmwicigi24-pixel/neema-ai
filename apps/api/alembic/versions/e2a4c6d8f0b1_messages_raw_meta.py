"""messages.raw_meta — what a non-plain inbound message IS, kept for the team.

Calls & audio programme, cycle 2 (2026-10-05). The dashboard showed "Message
can't be displayed (unsupported type)" 39 times in 30 days and the raw Meta
payload was never stored, so nobody could say what those messages were. This
nullable JSONB column holds, for every inbound message that is not plain text
or media (services/inbound_kinds.py): Meta's own `type`, our render `kind`
(location, contact, reaction, call-permission reply, unsupported, …), the
fields the dashboard draws a card from, Meta's `errors` (code / title /
details) and — for types we don't handle — a trimmed, PII-redacted copy of the
payload. NULL for every existing row and for plain text/media.

`ADD COLUMN IF NOT EXISTS` keeps the replay idempotent (app/main.py carries
the same statement), matching the translation migration before it.

Revision ID: e2a4c6d8f0b1
Revises: d1f3a5c7e9b2
"""
from alembic import op

revision = "e2a4c6d8f0b1"
down_revision = "d1f3a5c7e9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS raw_meta JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS raw_meta")
