"""production_enquiries — made-to-order requests from the public measurement form

Revision ID: d5e8f2a3b4c6
Revises: c3f7a1b9d2e4
Create Date: 2026-07-10

The ProductionEnquiry model shipped with NO migration (caught by the new
tests/test_migrations.py drift net) — the same class of bug as the
messages.comment_context outage. Created idempotently (IF NOT EXISTS) because
prod may or may not have gotten the table another way; either state converges.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e8f2a3b4c6"
down_revision: Union[str, Sequence[str], None] = "c3f7a1b9d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS production_enquiries (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ,
            product_slug VARCHAR(200),
            product_name VARCHAR(200),
            hub_product_id BIGINT,
            customer_name VARCHAR(200),
            phone VARCHAR(30),
            country_iso VARCHAR(5),
            measurements JSONB,
            notes TEXT,
            location VARCHAR(200),
            conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
            person_id UUID REFERENCES persons(id) ON DELETE SET NULL,
            status VARCHAR(20),
            hub_order_id BIGINT,
            hub_order_number VARCHAR(50)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_production_enquiries_created_at ON production_enquiries (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_production_enquiries_phone ON production_enquiries (phone)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_production_enquiries_conversation_id ON production_enquiries (conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_production_enquiries_status ON production_enquiries (status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS production_enquiries")
