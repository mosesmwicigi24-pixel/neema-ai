"""order_events: hub push linkage (Part B / Loop C)

Adds the columns that link a confirmed WhatsApp order-event to the order it
created in the Bethany House hub, so the push is idempotent (never double-pushes
a session) and Loop C can relay the receipt/payment link + answer "where's my
order?" from the hub order id.

Revision ID: d4b1f0a2c3e5
Revises: c2d3e4f5a6b7
Create Date: 2026-07-07 14:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4b1f0a2c3e5"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("order_events", sa.Column("hub_order_id", sa.Integer(), nullable=True))
    op.add_column("order_events", sa.Column("hub_order_number", sa.String(length=40), nullable=True))
    # null = never attempted; pushed | failed | skipped_dup | skipped_nomatch
    op.add_column("order_events", sa.Column("hub_push_status", sa.String(length=20), nullable=True))
    op.add_column("order_events", sa.Column("hub_payment_url", sa.Text(), nullable=True))
    op.add_column("order_events", sa.Column("hub_currency", sa.String(length=3), nullable=True))
    op.add_column("order_events", sa.Column("hub_total", sa.Numeric(12, 2), nullable=True))
    op.add_column("order_events", sa.Column("hub_last_error", sa.Text(), nullable=True))
    op.add_column("order_events", sa.Column("hub_pushed_at", sa.DateTime(timezone=True), nullable=True))
    # Look up "the pushed order for this session" quickly (idempotency + Loop C).
    op.create_index(
        "ix_order_events_session_hub_order",
        "order_events",
        ["session_id", "hub_order_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_order_events_session_hub_order", table_name="order_events")
    op.drop_column("order_events", "hub_pushed_at")
    op.drop_column("order_events", "hub_last_error")
    op.drop_column("order_events", "hub_total")
    op.drop_column("order_events", "hub_currency")
    op.drop_column("order_events", "hub_payment_url")
    op.drop_column("order_events", "hub_push_status")
    op.drop_column("order_events", "hub_order_number")
    op.drop_column("order_events", "hub_order_id")
