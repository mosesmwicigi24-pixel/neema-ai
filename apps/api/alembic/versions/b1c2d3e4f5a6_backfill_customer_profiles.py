"""backfill customer profiles: orphan conversations + null countries

Every conversation should have a backing user profile, and every user should
have a country resolved from their phone prefix. Historically neither was
guaranteed (upsert_message never created a user; country only landed via a
fragile n8n facts call), leaving ~800 conversations with no profile and ~70%
of users with a null country. This backfills both, deterministically, from
the server-side country table.

Idempotent: INSERT ... ON CONFLICT DO NOTHING and UPDATE ... WHERE country IS
NULL, so re-running is a no-op.

Revision ID: b1c2d3e4f5a6
Revises: a3e90c34e4ac
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.countries import resolve_country

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a3e90c34e4ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_STATE = '{"active":"active","cart":{"items":[],"subtotal":0}}'


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create a user row for every conversation that lacks one.
    orphans = conn.execute(sa.text(
        "SELECT DISTINCT c.wa_id FROM conversations c "
        "WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.wa_id = c.wa_id)"
    )).fetchall()
    for (wa_id,) in orphans:
        loc = resolve_country(wa_id)
        conn.execute(sa.text(
            "INSERT INTO users "
            "(id, wa_id, phone, name, name_confirmed, country, country_iso, flag_url, "
            " state, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :wa, :wa, '', false, :country, :iso, :flag, "
            " CAST(:state AS jsonb), now(), now()) "
            "ON CONFLICT (wa_id) DO NOTHING"
        ), {
            "wa": wa_id, "country": loc["country"], "iso": loc["country_iso"],
            "flag": loc["flag_url"], "state": _DEFAULT_STATE,
        })

    # 2. Resolve country for existing users that don't have one.
    null_country = conn.execute(sa.text(
        "SELECT wa_id FROM users WHERE country IS NULL OR country = ''"
    )).fetchall()
    for (wa_id,) in null_country:
        loc = resolve_country(wa_id)
        if not loc["country"]:
            continue
        conn.execute(sa.text(
            "UPDATE users SET country = :c, country_iso = :i, flag_url = :f "
            "WHERE wa_id = :wa AND (country IS NULL OR country = '')"
        ), {"c": loc["country"], "i": loc["country_iso"], "f": loc["flag_url"], "wa": wa_id})


def downgrade() -> None:
    # Data backfill — nothing to reverse. Orphan users and resolved countries
    # are legitimate data; leave them in place.
    pass
