"""app_settings — operator-editable KV (standing orders first).

Revision ID: e6a1b2c3d4f5
Revises: c5f8d2e3a9b1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6a1b2c3d4f5"
down_revision: Union[str, Sequence[str], None] = "c5f8d2e3a9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
