"""voice transcripts — status + language on messages; room for failure reasons on calls

Every inbound voice note now carries its transcription outcome on the row
(services/voice_notes.py): the verbatim words stay in `messages.text` (the
contract the dashboard, the agent's history and previews already read), and
these columns say what happened and in which language:

  messages.transcript_status  none | queued | done | silent | failed:<reason>
  messages.transcript_lang    ISO-639-1 of the spoken language ("sw", "en")

calls.transcript_status widens from 20 to 40 characters so the lifecycle can
name its reason (`failed:provider_timeout` is 23).

Revision ID: 36ed77bde344
Revises: d1f3a5c7e9b2
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "36ed77bde344"
down_revision: Union[str, Sequence[str], None] = "d1f3a5c7e9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS transcript_status VARCHAR(40)")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS transcript_lang VARCHAR(12)")
    op.execute("ALTER TABLE calls ALTER COLUMN transcript_status TYPE VARCHAR(40)")


def downgrade() -> None:
    op.execute("UPDATE calls SET transcript_status = 'failed' WHERE length(transcript_status) > 20")
    op.execute("ALTER TABLE calls ALTER COLUMN transcript_status TYPE VARCHAR(20)")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS transcript_lang")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS transcript_status")
