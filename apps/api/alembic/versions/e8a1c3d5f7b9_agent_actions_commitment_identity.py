"""agent_actions.dedupe_key + source — one open row per commitment

Revision ID: e8a1c3d5f7b9
Revises: d7f9b1c3e5a7
Create Date: 2026-11-05

Audit, 2026-11-05: a customer heard from Neema five times about one matter
because every planner (the scribe, the schedule_check_in tool, the fit-check
planner) filed its own row and nothing said two rows were the same
commitment. The identity now lives on the row (`dedupe_key`), the planner's
name beside it (`source`), and a partial unique index makes a second open row
for the same commitment impossible — whichever worker, whichever path.

Order of work, so the index can be created on a live table:
  1. add the columns (idempotent);
  2. backfill keys for every OPEN row from its kind/reason (the same rules as
     app.services.actions.dedupe_key_for, inlined here so the migration never
     depends on code that moves on);
  3. merge open duplicates: the newest booking (the customer's latest word)
     stays, the others are vetoed with a reason that says so;
  4. create the index.

Downgrade drops the index and the columns; vetoed duplicates stay vetoed
(they were duplicates).
"""
from __future__ import annotations

import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8a1c3d5f7b9"
down_revision: Union[str, Sequence[str], None] = "d7f9b1c3e5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPEN = ("planned", "needs_approval", "sending")
UNIQUE_INDEX_SQL = """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_actions_open_commitment
        ON agent_actions (conversation_id, dedupe_key)
     WHERE status IN ('planned', 'needs_approval', 'sending')
       AND dedupe_key IS NOT NULL AND conversation_id IS NOT NULL
"""
_ORDER_RE = re.compile(r"\b(?:order|#)\s*#?([A-Z]{1,6}-?\d{1,8}|\d{3,10})\b", re.IGNORECASE)


def _key(kind: str, reason: str | None, deal_id, conversation_id) -> str:
    base = str(deal_id or conversation_id or "")
    r = reason or ""
    if kind in ("quote_follow_up", "buying_follow_up"):
        return f"buying:{base}"
    if kind == "follow_up":
        return f"promise:{base}"
    if kind == "customer_promise":
        return f"customer_promise:{base}"
    if kind == "check_in":
        return "check_in:delivery" if r.startswith("Delivery check-in") else "check_in:purchase_decision"
    if kind == "replenishment":
        return "check_in:supplies" if r.startswith("Supplies check-in") else "check_in:purchase_decision"
    if kind == "fit_check":
        m = _ORDER_RE.search(r)
        return f"care:{m.group(1) if m else base}"
    return f"{kind}:{base}"


def upgrade() -> None:
    op.execute("ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(80)")
    op.execute("ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS source VARCHAR(30)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_actions_dedupe_key ON agent_actions (dedupe_key)")

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, kind, reason, deal_id, conversation_id FROM agent_actions "
        "WHERE status IN :open AND dedupe_key IS NULL").bindparams(
            sa.bindparam("open", value=OPEN, expanding=True))).fetchall()
    for rid, kind, reason, deal_id, conv_id in rows:
        conn.execute(sa.text("UPDATE agent_actions SET dedupe_key = :k WHERE id = :id"),
                     {"k": _key(kind or "", reason, deal_id, conv_id)[:80], "id": rid})

    # Merge: keep the newest open booking per (conversation, key); veto the rest.
    conn.execute(sa.text("""
        WITH ranked AS (
            SELECT id, row_number() OVER (
                       PARTITION BY conversation_id, dedupe_key
                       ORDER BY created_at DESC, id DESC) AS rn
              FROM agent_actions
             WHERE status IN ('planned', 'needs_approval', 'sending')
               AND dedupe_key IS NOT NULL AND conversation_id IS NOT NULL
        )
        UPDATE agent_actions a
           SET status = 'vetoed',
               reason = left(coalesce(a.reason, '') ||
                             ' [merged: duplicate of the same commitment — migration e8a1c3d5f7b9]', 1000)
          FROM ranked r
         WHERE a.id = r.id AND r.rn > 1
    """))

    op.execute(UNIQUE_INDEX_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_agent_actions_open_commitment")
    op.execute("DROP INDEX IF EXISTS ix_agent_actions_dedupe_key")
    op.execute("ALTER TABLE agent_actions DROP COLUMN IF EXISTS source")
    op.execute("ALTER TABLE agent_actions DROP COLUMN IF EXISTS dedupe_key")
