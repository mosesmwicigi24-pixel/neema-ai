"""interceptaction gains 'pause' — the timeline value the Pause button writes.

The dashboard always OFFERED Pause, but no pause endpoint existed: the button
was wired to release(), which hands the thread back to the AI — the opposite
of pausing (found 2026-08-19, the owner's button audit). The new
pause_conversation journals an Intercept row with this action.

ALTER TYPE … ADD VALUE cannot run inside a transaction, so it rides alembic's
autocommit block. IF NOT EXISTS keeps the replay idempotent.

Revision ID: f0a1b2c3d4e5
Revises: e7f8a9b0c1d2
"""
from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE interceptaction ADD VALUE IF NOT EXISTS 'pause'")


def downgrade() -> None:
    # Postgres enums can't drop values; existing 'pause' rows keep meaning.
    pass
