"""push_devices — phones that ring for incoming calls with the app closed (FCM tokens)

Revision ID: e4b6d8f0a2c4
Revises: b8d0f2a4c6e9
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e4b6d8f0a2c4"
down_revision: Union[str, Sequence[str], None] = "b8d0f2a4c6e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS push_devices (
            id           UUID PRIMARY KEY,
            token        VARCHAR(512) NOT NULL,
            agent_id     VARCHAR(64)  NOT NULL,
            platform     VARCHAR(16)  NOT NULL DEFAULT 'android',
            app_version  VARCHAR(40)  NOT NULL DEFAULT '',
            device       VARCHAR(120) NOT NULL DEFAULT '',
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_push_devices_token ON push_devices (token)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_push_devices_agent_id ON push_devices (agent_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS push_devices")
