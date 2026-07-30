"""agent_feedback + qa_findings — the learning loops.

Revision ID: b7c8d9e0f1a2
Revises: a1c2d3e4f5b6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1c2d3e4f5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("sent", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_feedback_conversation_id", "agent_feedback", ["conversation_id"])
    op.create_index("ix_agent_feedback_created_at", "agent_feedback", ["created_at"])
    op.create_table(
        "qa_findings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_qa_findings_conversation_id", "qa_findings", ["conversation_id"])
    op.create_index("ix_qa_findings_kind", "qa_findings", ["kind"])
    op.create_index("ix_qa_findings_created_at", "qa_findings", ["created_at"])


def downgrade() -> None:
    op.drop_table("qa_findings")
    op.drop_table("agent_feedback")
