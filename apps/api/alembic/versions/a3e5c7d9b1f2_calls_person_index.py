"""calls — index person_id (thread / customer panel / agent context read calls by person)

Revision ID: a3e5c7d9b1f2
Revises: c4a7e2b9d1f3
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a3e5c7d9b1f2"
down_revision: Union[str, Sequence[str], None] = "c4a7e2b9d1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every conversation open asks for `wa_id = … OR person_id = …`; without
    # this index the OR falls back to a full scan of calls.
    op.execute("CREATE INDEX IF NOT EXISTS ix_calls_person_id ON calls (person_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_calls_person_id")
