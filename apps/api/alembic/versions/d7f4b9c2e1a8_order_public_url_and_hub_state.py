"""order_events: the durable customer link + mirrored hub state

The link Neema handed customers was a tap-to-order shortlink pointing at a
storefront product page, and once its redis ref expired it 302'd to a bare
wa.me chat — that is what a customer saw when told "here's your order link".
The only order-shaped URL Neema ever stored was hub_payment_url, a 72-hour pay
session: all 88 that were ever sent are expired.

hub_public_url is the hub's durable /order/{public_token} — the receipt when
paid, the checkout when not, working years later.

The hub_* state columns mirror what the hub says about the order. They are
DELIBERATELY separate from OrderEvent.status, which is an operator's own triage
flag set by hand in the Orders modal — overwriting it would destroy human work.
The screen shows hub truth when the order is linked, and the local flag
otherwise.

Revision ID: d7f4b9c2e1a8
Revises: f0a1b2c3d4e5
"""
from alembic import op
import sqlalchemy as sa

revision = "d7f4b9c2e1a8"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_events", sa.Column("hub_public_url", sa.Text(), nullable=True))
    op.add_column("order_events", sa.Column("hub_public_token", sa.String(64), nullable=True))
    op.add_column("order_events", sa.Column("short_ref", sa.String(12), nullable=True))
    op.add_column("order_events", sa.Column("hub_status", sa.String(24), nullable=True))
    op.add_column("order_events", sa.Column("hub_payment_status", sa.String(24), nullable=True))
    op.add_column("order_events", sa.Column("hub_fulfillment_status", sa.String(24), nullable=True))
    op.add_column("order_events", sa.Column("hub_status_at", sa.DateTime(timezone=True), nullable=True))

    # short_ref backs /api/r/{ref}. Unique so a ref resolves to exactly one
    # order; partial so the 196 rows that were never pushed (cart snapshots)
    # do not all collide on NULL.
    op.create_index("ix_order_events_short_ref", "order_events", ["short_ref"],
                    unique=True, postgresql_where=sa.text("short_ref IS NOT NULL"))
    # The hub-event mirror looks rows up by hub order id or number.
    op.create_index("ix_order_events_hub_order_id", "order_events", ["hub_order_id"],
                    postgresql_where=sa.text("hub_order_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_order_events_hub_order_id", table_name="order_events")
    op.drop_index("ix_order_events_short_ref", table_name="order_events")
    for col in ("hub_status_at", "hub_fulfillment_status", "hub_payment_status",
                "hub_status", "short_ref", "hub_public_token", "hub_public_url"):
        op.drop_column("order_events", col)
