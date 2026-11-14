"""Clear the stale approval backlog (owner, 2026-11-14: "clear").

Rows that have waited for a person's approval for more than 30 days will
never be sent usefully: the customer's reply window closed weeks ago and the
moment each follow-up was written for has passed. On 14 Nov 2026 there were
636 rows waiting, about 450 of them older than 30 days.

They are marked `vetoed` with a reason that names this clearance, so the
record stays readable and the downgrade can put exactly these rows back.
Rows from the last 30 days are left for the team.

Revision ID: b1d3f5a7c9e2
Revises: a9c1e3f5b7d9
"""
from alembic import op

revision = "b1d3f5a7c9e2"
down_revision = "a9c1e3f5b7d9"
branch_labels = None
depends_on = None

MARK = " [cleared 2026-11-14 on the owner's word: waited over 30 days for approval]"


def upgrade() -> None:
    op.execute(
        "UPDATE agent_actions "
        "SET status = 'vetoed', reason = COALESCE(reason, '') || '" + MARK.replace("'", "''") + "' "
        "WHERE status = 'needs_approval' AND created_at < now() - interval '30 days'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE agent_actions "
        "SET status = 'needs_approval', reason = replace(reason, '" + MARK.replace("'", "''") + "', '') "
        "WHERE status = 'vetoed' AND reason LIKE '%" + MARK.replace("'", "''").replace("%", "") + "'"
    )
