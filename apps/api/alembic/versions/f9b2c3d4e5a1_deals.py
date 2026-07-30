"""deals — Neema owns outcomes, visibly.

Revision ID: f9b2c3d4e5a1
Revises: e6a1b2c3d4f5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "f9b2c3d4e5a1"
down_revision: Union[str, Sequence[str], None] = "e6a1b2c3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("person_id", UUID(as_uuid=True),
                  sa.ForeignKey("persons.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("items_snapshot", JSONB(), nullable=False, server_default="[]"),
        sa.Column("stage", sa.String(length=30), nullable=False, server_default="new"),
        sa.Column("blocking", sa.Text(), nullable=True),
        sa.Column("next_action", JSONB(), nullable=True),
        sa.Column("guidance", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_deals_person_id", "deals", ["person_id"])
    op.create_index("ix_deals_conversation_id", "deals", ["conversation_id"])
    op.create_index("ix_deals_stage", "deals", ["stage"])
    op.create_index("ix_deals_status", "deals", ["status"])


def downgrade() -> None:
    op.drop_table("deals")
