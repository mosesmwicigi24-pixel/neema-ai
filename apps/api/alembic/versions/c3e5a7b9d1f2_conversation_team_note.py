"""One team note per conversation (owner, 2026-11-15).

Notes used to pile up in the chat as separate yellow cards: "too many and too
long". A thread now carries ONE note the team edits in place, shown in a
floating panel above the reply box. Older note rows stay in `messages` and
appear in that panel's history; nothing is deleted.

Like every internal note, the team note never reaches the model.

Revision ID: c3e5a7b9d1f2
Revises: b1d3f5a7c9e2
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3e5a7b9d1f2"
down_revision = "b1d3f5a7c9e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("team_note", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column(
        "team_note_by", postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True))
    op.add_column("conversations", sa.Column(
        "team_note_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "team_note_at")
    op.drop_column("conversations", "team_note_by")
    op.drop_column("conversations", "team_note")
