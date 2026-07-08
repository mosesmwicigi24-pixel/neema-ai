"""identity spine — persons + identities, person_id/channel backfill

Introduces the identity spine (docs/MULTICHANNEL_IDENTITY_PLAN.md):

  * `persons`     — the human; the stable CRM unit.
  * `identities`  — one (channel, external_id) handle; UNIQUE(channel, external_id);
                    many identities roll up to one person.

Adds a nullable `person_id` to users, conversations, messages, order_events and
customer_history, plus a `channel` (default whatsapp) to conversations and
messages (order_events already had one). Then BACKFILLS: every distinct wa_id
becomes exactly one person + one (whatsapp, wa_id) identity, and every wa_id-keyed
row is stamped with that person_id.

This is purely additive and reversible. Nothing reads person_id yet, and
UNIQUE(conversations.wa_id) is intentionally left in place — so WhatsApp keeps
working byte-for-byte. Backfill maps by the *literal* stored wa_id string (rows
sharing a wa_id share a person); unreachable legacy variants simply get their own
person, which is harmless.

Revision ID: e5c2b7a1d9f0
Revises: d4b1f0a2c3e5
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5c2b7a1d9f0"
down_revision: Union[str, Sequence[str], None] = "d4b1f0a2c3e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables that carry a wa_id and gain a person_id. (table, wa_id_col)
_WA_TABLES = [
    "users",
    "conversations",
    "messages",
    "order_events",
    "customer_history",
]


def upgrade() -> None:
    # ── 1. persons ────────────────────────────────────────────────────────────
    op.create_table(
        "persons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("merged_into_id", sa.Uuid(), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["merged_into_id"], ["persons.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_persons_merged_into_id", "persons", ["merged_into_id"])

    # ── 2. identities ─────────────────────────────────────────────────────────
    op.create_table(
        "identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("raw_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("channel", "external_id", name="uq_identity_channel_external_id"),
    )
    op.create_index("ix_identities_person_id", "identities", ["person_id"])

    # ── 3. additive columns on the wa_id-keyed tables ─────────────────────────
    op.add_column("users", sa.Column("person_id", sa.Uuid(), nullable=True))
    op.add_column("conversations", sa.Column("channel", sa.String(length=20),
                  nullable=True, server_default="whatsapp"))
    op.add_column("conversations", sa.Column("person_id", sa.Uuid(), nullable=True))
    op.add_column("messages", sa.Column("channel", sa.String(length=20),
                  nullable=True, server_default="whatsapp"))
    op.add_column("messages", sa.Column("person_id", sa.Uuid(), nullable=True))
    op.add_column("order_events", sa.Column("person_id", sa.Uuid(), nullable=True))
    op.add_column("customer_history", sa.Column("person_id", sa.Uuid(), nullable=True))

    for tbl in _WA_TABLES:
        op.create_index(f"ix_{tbl}_person_id", tbl, ["person_id"])
        op.create_foreign_key(
            f"fk_{tbl}_person_id", tbl, "persons",
            ["person_id"], ["id"], ondelete="SET NULL",
        )

    # ── 4. backfill: one person + one (whatsapp, wa_id) identity per wa_id ─────
    # Set-based, inside this migration's transaction. gen_random_uuid() is core
    # in PostgreSQL 13+. A temp table maps wa_id → the new person id so every
    # wa_id-keyed row can be stamped consistently.
    op.execute(sa.text("""
        CREATE TEMPORARY TABLE _wa_person_map (
            wa_id     varchar(30) PRIMARY KEY,
            person_id uuid NOT NULL DEFAULT gen_random_uuid()
        ) ON COMMIT DROP;
    """))
    op.execute(sa.text("""
        INSERT INTO _wa_person_map (wa_id)
        SELECT wa_id FROM (
            SELECT wa_id FROM users            WHERE wa_id IS NOT NULL AND wa_id <> ''
            UNION SELECT wa_id FROM conversations    WHERE wa_id IS NOT NULL AND wa_id <> ''
            UNION SELECT wa_id FROM messages         WHERE wa_id IS NOT NULL AND wa_id <> ''
            UNION SELECT wa_id FROM order_events     WHERE wa_id IS NOT NULL AND wa_id <> ''
            UNION SELECT wa_id FROM customer_history WHERE wa_id IS NOT NULL AND wa_id <> ''
        ) u;
    """))

    # persons: carry the user's display name where one exists.
    op.execute(sa.text("""
        INSERT INTO persons (id, display_name, state, created_at, updated_at)
        SELECT m.person_id, u.name, '{}'::jsonb, now(), now()
        FROM _wa_person_map m
        LEFT JOIN users u ON u.wa_id = m.wa_id;
    """))
    # identities: one (whatsapp, wa_id) per person. A phone IS the person in
    # World A → source=backfill, confidence=deterministic.
    op.execute(sa.text("""
        INSERT INTO identities
            (id, person_id, channel, external_id, display_name,
             raw_profile, source, confidence, created_at, updated_at)
        SELECT gen_random_uuid(), m.person_id, 'whatsapp', m.wa_id, u.name,
               '{}'::jsonb, 'backfill', 'deterministic', now(), now()
        FROM _wa_person_map m
        LEFT JOIN users u ON u.wa_id = m.wa_id;
    """))

    # stamp person_id everywhere.
    for tbl in _WA_TABLES:
        op.execute(sa.text(f"""
            UPDATE {tbl} t SET person_id = m.person_id
            FROM _wa_person_map m WHERE t.wa_id = m.wa_id;
        """))
    # _wa_person_map is ON COMMIT DROP — Alembic commits at the end of the migration.


def downgrade() -> None:
    for tbl in _WA_TABLES:
        op.drop_constraint(f"fk_{tbl}_person_id", tbl, type_="foreignkey")
        op.drop_index(f"ix_{tbl}_person_id", table_name=tbl)

    op.drop_column("customer_history", "person_id")
    op.drop_column("order_events", "person_id")
    op.drop_column("messages", "person_id")
    op.drop_column("messages", "channel")
    op.drop_column("conversations", "person_id")
    op.drop_column("conversations", "channel")
    op.drop_column("users", "person_id")

    op.drop_index("ix_identities_person_id", table_name="identities")
    op.drop_table("identities")
    op.drop_index("ix_persons_merged_into_id", table_name="persons")
    op.drop_table("persons")
