"""agent_actions — Neema's initiative queue with a veto window.

Revision ID: a1c2d3e4f5b6
Revises: f9b2c3d4e5a1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a1c2d3e4f5b6"
down_revision: Union[str, Sequence[str], None] = "f9b2c3d4e5a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("deal_id", UUID(as_uuid=True),
                  sa.ForeignKey("deals.id", ondelete="CASCADE"), nullable=True),
        sa.Column("conversation_id", UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False, server_default="follow_up"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("draft", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="planned"),
        sa.Column("created_by", sa.String(length=10), nullable=False, server_default="ai"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_actions_deal_id", "agent_actions", ["deal_id"])
    op.create_index("ix_agent_actions_conversation_id", "agent_actions", ["conversation_id"])
    op.create_index("ix_agent_actions_due_at", "agent_actions", ["due_at"])
    op.create_index("ix_agent_actions_status", "agent_actions", ["status"])


def downgrade() -> None:
    op.drop_table("agent_actions")
