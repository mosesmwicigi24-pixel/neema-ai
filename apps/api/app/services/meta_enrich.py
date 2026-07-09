"""Backfill name + photo for Meta contacts that came in "Unknown".

Live enrichment (routers/meta_webhook) only fires when a contact messages, and
it was silently returning nothing until the Meta app was approved for
`pages_messaging`. So the inbox carries a backlog of anonymous Messenger /
Instagram / Facebook rows whose person has no display_name. This re-runs the
Profile API for those — retroactively naming + picturing them — so the operator
isn't staring at a wall of "Unknown".

Best-effort and bounded: a Profile API miss (privacy-restricted user, unknown
id) just leaves that row as-is; the batch limit keeps us well inside Meta's
rate limits. Idempotent — a named row is skipped next time.
"""
import logging

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.person import Person, Identity
from app.services.meta_send import fetch_profile

_log = logging.getLogger("neema.meta")

# Identity channels that resolve via the Meta Profile API (PSID / IGSID).
_META_CHANNELS = ("messenger", "instagram", "facebook")


async def backfill_unknown_profiles(db: AsyncSession, limit: int = 50) -> dict:
    """Enrich up to `limit` still-nameless Meta contacts. Returns a small summary
    ({attempted, enriched, scanned}); commits once at the end."""
    rows = (await db.execute(
        select(Identity, Person)
        .join(Person, Person.id == Identity.person_id)
        .where(Identity.channel.in_(_META_CHANNELS))
        .where(or_(Person.display_name.is_(None), Person.display_name == ""))
        .where(Person.merged_into_id.is_(None))       # skip tombstoned duplicates
        .order_by(Identity.created_at.desc())          # newest (most likely to matter) first
        .limit(limit)
    )).all()

    attempted = 0
    enriched = 0
    for ident, person in rows:
        attempted += 1
        prof = await fetch_profile(ident.external_id)   # {} on any failure
        name = (prof.get("name") or "").strip()
        pic = prof.get("profile_pic")
        if not name and not pic:
            continue
        if name:
            if not person.display_name:
                person.display_name = name[:200]
            if not ident.display_name:
                ident.display_name = name[:200]
        if pic and (ident.raw_profile or {}).get("profile_pic") != pic:
            ident.raw_profile = {**(ident.raw_profile or {}), "profile_pic": pic}
        enriched += 1

    if enriched:
        await db.commit()
    _log.info("meta profile backfill: enriched %d/%d nameless contact(s)", enriched, attempted)
    return {"attempted": attempted, "enriched": enriched, "scanned": len(rows)}
