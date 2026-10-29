"""photo_checks — one row per customer photo checked against what we sell

Revision ID: a4c6e8f0b2d4
Revises: f3a5c7e9b1d2
Create Date: 2026-10-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a4c6e8f0b2d4"
down_revision: Union[str, Sequence[str], None] = "f3a5c7e9b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS photo_checks (
            id               UUID PRIMARY KEY,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            channel          VARCHAR(20)  NOT NULL DEFAULT 'whatsapp',
            contact          VARCHAR(128) NOT NULL,
            conversation_id  UUID REFERENCES conversations(id) ON DELETE SET NULL,
            message_id       UUID REFERENCES messages(id) ON DELETE SET NULL,
            media_url        TEXT,
            image_sha        VARCHAR(40),
            verdict          VARCHAR(16)  NOT NULL,
            product          VARCHAR(200),
            product_slug     VARCHAR(200),
            match            VARCHAR(8),
            ai_made          VARCHAR(10),
            extra_embroidery BOOLEAN,
            reasons          JSONB,
            source           VARCHAR(16),
            mode             VARCHAR(8)   NOT NULL DEFAULT 'shadow',
            acted            BOOLEAN      NOT NULL DEFAULT false,
            owner_mark       VARCHAR(8),
            owner_note       TEXT,
            marked_by        UUID REFERENCES agents(id) ON DELETE SET NULL,
            marked_at        TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_photo_checks_created_at ON photo_checks (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_photo_checks_verdict ON photo_checks (verdict)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_photo_checks_image_sha ON photo_checks (image_sha)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_photo_checks_conversation_id ON photo_checks (conversation_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS photo_checks")
