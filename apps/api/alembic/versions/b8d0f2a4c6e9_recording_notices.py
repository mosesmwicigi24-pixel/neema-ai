"""recording_notices — who has had the written call-recording notice (once each)

services/recording_notice.py sends a one-line written notice ("calls may be
recorded and transcribed") the first time a customer's call connects, when
CALL_RECORDING_NOTICE_ENABLED is on (off by default). The (channel,
recipient) primary key is the once-per-customer guarantee.

Revision ID: b8d0f2a4c6e9
Revises: 36ed77bde344
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b8d0f2a4c6e9"
down_revision: Union[str, Sequence[str], None] = "36ed77bde344"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS recording_notices (
            channel VARCHAR(20) NOT NULL,
            recipient VARCHAR(64) NOT NULL,
            call_id VARCHAR(200),
            sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (channel, recipient)
        )""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recording_notices")
