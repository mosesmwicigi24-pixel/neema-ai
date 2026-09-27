"""calls — link a WhatsApp voicemail to its call

Revision ID: b6d8e0f2a4c7
Revises: a3e5c7d9b1f2
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b6d8e0f2a4c7"
down_revision: Union[str, Sequence[str], None] = "a3e5c7d9b1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Voicemail arrives as an inbound audio message whose id is the call's WACID.
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS voicemail_message_id VARCHAR(200)")


def downgrade() -> None:
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS voicemail_message_id")
