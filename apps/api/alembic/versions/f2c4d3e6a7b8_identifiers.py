"""identifiers — phone/email/order-ref tokens that bind a channel to a person

The second half of the spine architecture (docs/MULTICHANNEL_IDENTITY_PLAN.md):
`identity(channel, external_id)` is a messaging surface; `identifier(type, value)`
is a portable token — a volunteered/matched phone or email, an M-Pesa payer
MSISDN, an order number quoted cross-channel. `UNIQUE(type, value)` → one token
maps to one person. Powers the M-Pesa payment→person reconciler (lever 2) and
order-ref tokens (lever 3). Additive only.

Revision ID: f2c4d3e6a7b8
Revises: f1b3c2d4e5a6
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f2c4d3e6a7b8"
down_revision: Union[str, Sequence[str], None] = "f1b3c2d4e5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "identifiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),        # phone | email | mpesa_ref | order_number
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=True),       # mpesa_payment | volunteered | hub …
        sa.Column("confidence", sa.String(length=20), nullable=True),   # deterministic | assisted | weak
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("type", "value", name="uq_identifier_type_value"),
    )
    op.create_index("ix_identifiers_person_id", "identifiers", ["person_id"])

    # A merge now also moves the secondary's identifiers onto the primary; record
    # which ones so unmerge can reverse it exactly.
    op.add_column("person_merges", sa.Column(
        "moved_identifier_ids", postgresql.JSONB(astext_type=sa.Text()),
        nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("person_merges", "moved_identifier_ids")
    op.drop_index("ix_identifiers_person_id", table_name="identifiers")
    op.drop_table("identifiers")
