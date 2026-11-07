"""interceptaction gains 'flag' and 'escalated' — the two timeline values the
code has written since the Activity timeline existed, which no migration ever
added to the Postgres type (the initial migration created four values; only
'pause' was added later). On a database built from the migrations every
opt-out record, held-reply flag and escalation write raised
`invalid input value for enum interceptaction: "flag"` — found by the
first real-model evaluation run (42289125585, 2026-11-06).

ALTER TYPE … ADD VALUE cannot run inside a transaction, so it rides alembic's
autocommit block. IF NOT EXISTS keeps the replay idempotent and makes this a
no-op on a database that already has the values.

Revision ID: a9c1e3f5b7d9
Revises: e8a1c3d5f7b9
"""
from alembic import op

revision = "a9c1e3f5b7d9"
down_revision = "e8a1c3d5f7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE interceptaction ADD VALUE IF NOT EXISTS 'flag'")
        op.execute("ALTER TYPE interceptaction ADD VALUE IF NOT EXISTS 'escalated'")


def downgrade() -> None:
    # Postgres enums can't drop values; existing rows keep their meaning.
    pass
