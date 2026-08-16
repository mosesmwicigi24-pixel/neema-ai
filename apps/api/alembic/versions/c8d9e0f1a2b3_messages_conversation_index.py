"""Index messages(conversation_id, created_at) — the dashboard's hottest path.

The inbox was getting slower and hanging on interaction. Cause: Postgres does
not index a foreign key automatically, and `messages.conversation_id` had no
index while every other table's conversation_id did. So the three inbox
aggregate queries (latest message, last outbound, unread count) and — worse —
opening any single chat (`WHERE conversation_id = ? ORDER BY created_at`) each
sequentially scanned the ENTIRE messages table. That cost grows with every
message the business ever exchanges, on every channel, which is exactly the
"it used to be fine, now it hangs" shape.

Composite rather than a bare conversation_id index: the trailing created_at
lets the same index satisfy the ORDER BY and the MAX(created_at) grouping
without a separate sort.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""
from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None

_NAME = "ix_messages_conversation_id_created_at"


def upgrade() -> None:
    # if_not_exists: the index may already have been added by hand on a box
    # that was hurting before this shipped — the migration must still pass.
    op.execute(
        f'CREATE INDEX IF NOT EXISTS {_NAME} ON messages (conversation_id, created_at)'
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_NAME}")
