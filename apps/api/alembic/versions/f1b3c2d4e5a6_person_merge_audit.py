"""person_merges — reversible merge audit

Records each real (person-level) merge so it can be undone: which identities
moved, which wa_ids' denormalized person_id cache was refreshed, who did it and
when. See app/services/merge.py + docs/MULTICHANNEL_IDENTITY_PLAN.md
("Reconciliation as a confidence ladder … reversibly and auditably").

Additive only.

Revision ID: f1b3c2d4e5a6
Revises: e5c2b7a1d9f0
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f1b3c2d4e5a6"
down_revision: Union[str, Sequence[str], None] = "e5c2b7a1d9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "person_merges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("primary_person_id", sa.Uuid(), nullable=False),
        sa.Column("secondary_person_id", sa.Uuid(), nullable=False),
        # The identities that moved secondary→primary, and the external_ids
        # (wa_ids) whose denormalized person_id was refreshed — everything unmerge
        # needs to reverse the move exactly.
        sa.Column("moved_identity_ids", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("moved_external_ids", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("primary_wa_id", sa.String(length=30), nullable=True),
        sa.Column("secondary_wa_id", sa.String(length=30), nullable=True),
        sa.Column("performed_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["primary_person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secondary_person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["performed_by"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["undone_by"], ["agents.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_person_merges_primary_person_id", "person_merges", ["primary_person_id"])
    op.create_index("ix_person_merges_secondary_person_id", "person_merges", ["secondary_person_id"])


def downgrade() -> None:
    op.drop_index("ix_person_merges_secondary_person_id", table_name="person_merges")
    op.drop_index("ix_person_merges_primary_person_id", table_name="person_merges")
    op.drop_table("person_merges")
