"""calls — the channel a call came on (whatsapp | messenger) + its handle

Revision ID: c7e9f1a3b5d8
Revises: b6d8e0f2a4c7
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c7e9f1a3b5d8"
down_revision: Union[str, Sequence[str], None] = "b6d8e0f2a4c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every existing row is a WhatsApp call. A Messenger call keeps wa_id NULL
    # and carries the customer's PSID in external_id.
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS channel VARCHAR(20) NOT NULL DEFAULT 'whatsapp'")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS external_id VARCHAR(64)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_calls_external_id ON calls (external_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_calls_external_id")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS external_id")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS channel")
