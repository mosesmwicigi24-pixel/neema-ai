"""channel-native conversations — external_id + UNIQUE(channel, external_id)

The query-layer cutover (docs/MULTICHANNEL_IDENTITY_PLAN.md): let a conversation
belong to any channel, not just WhatsApp. Adds `external_id` (the channel-native
handle: wa_id | Messenger PSID | Instagram IGSID) to conversations + messages,
backfilled from wa_id; replaces the unique `wa_id` index with
`UNIQUE(channel, external_id)` (same one-conv-per-wa_id guarantee for WhatsApp,
extended to other channels); makes `wa_id` nullable (NULL for non-phone channels).

WhatsApp is unchanged: every existing row keeps its wa_id, and external_id == wa_id,
so the old `Conversation.wa_id == wa_id` lookups (the compat shim) still resolve.

Reversible on WhatsApp-only data. NOTE: once Messenger/IG rows exist (NULL wa_id),
`downgrade()` can't restore wa_id NOT NULL — expected for a forward cutover.

Revision ID: a1b2c3d4e5f6
Revises: f2c4d3e6a7b8
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f2c4d3e6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── conversations ─────────────────────────────────────────────────────────
    op.add_column("conversations", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.execute("UPDATE conversations SET external_id = wa_id WHERE external_id IS NULL")
    op.execute("UPDATE conversations SET channel = 'whatsapp' WHERE channel IS NULL")
    op.alter_column("conversations", "external_id", existing_type=sa.String(length=128), nullable=False)
    op.alter_column("conversations", "channel", existing_type=sa.String(length=20),
                    nullable=False, server_default="whatsapp")

    # Swap the UNIQUE wa_id index for a plain one (wa_id is now nullable and no
    # longer the key), and add the new natural key.
    op.drop_index("ix_conversations_wa_id", table_name="conversations")
    op.alter_column("conversations", "wa_id", existing_type=sa.String(length=30), nullable=True)
    op.create_index("ix_conversations_wa_id", "conversations", ["wa_id"])
    op.create_unique_constraint(
        "uq_conversation_channel_external_id", "conversations", ["channel", "external_id"]
    )

    # ── messages ──────────────────────────────────────────────────────────────
    op.add_column("messages", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.execute("UPDATE messages SET external_id = wa_id WHERE external_id IS NULL")
    op.execute("UPDATE messages SET channel = 'whatsapp' WHERE channel IS NULL")
    op.alter_column("messages", "channel", existing_type=sa.String(length=20),
                    nullable=False, server_default="whatsapp")
    op.alter_column("messages", "wa_id", existing_type=sa.String(length=30), nullable=True)
    op.create_index("ix_messages_external_id", "messages", ["external_id"])


def downgrade() -> None:
    # messages
    op.drop_index("ix_messages_external_id", table_name="messages")
    op.execute("UPDATE messages SET wa_id = external_id WHERE wa_id IS NULL")
    op.alter_column("messages", "wa_id", existing_type=sa.String(length=30), nullable=False)
    op.alter_column("messages", "channel", existing_type=sa.String(length=20),
                    nullable=True, server_default="whatsapp")
    op.drop_column("messages", "external_id")

    # conversations
    op.drop_constraint("uq_conversation_channel_external_id", "conversations", type_="unique")
    op.execute("UPDATE conversations SET wa_id = external_id WHERE wa_id IS NULL")
    op.drop_index("ix_conversations_wa_id", table_name="conversations")
    op.alter_column("conversations", "wa_id", existing_type=sa.String(length=30), nullable=False)
    op.create_index("ix_conversations_wa_id", "conversations", ["wa_id"], unique=True)
    op.alter_column("conversations", "channel", existing_type=sa.String(length=20),
                    nullable=True, server_default="whatsapp")
    op.drop_column("conversations", "external_id")
