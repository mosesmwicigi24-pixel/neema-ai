"""One-shot: name the 'Unknown' Meta (Messenger/IG/Facebook) contacts via the
Profile API, right now — instead of waiting for the slow background backfill.

Walks the whole nameless backlog in batches; contacts the Profile API can't name
are stamped so each batch advances. Prints per-batch + a total, so you can SEE
whether the Profile API is actually returning names (enriched > 0) or being
blocked (enriched 0, marked N — then check the api logs for the Graph error).

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.enrich_names
"""
from __future__ import annotations

import asyncio
import logging

# Full model registry so the mappers configure in this standalone interpreter.
import app.models.agent      # noqa: F401
import app.models.conversation  # noqa: F401
import app.models.intercept  # noqa: F401
import app.models.message    # noqa: F401
import app.models.person     # noqa: F401
import app.models.user       # noqa: F401
from app.database import AsyncSessionLocal
from app.services.meta_enrich import backfill_unknown_profiles

_log = logging.getLogger("neema.enrich")


async def _sweep_conversation_names() -> int:
    """Phase 1: name the backlog from the page-level Conversations API — the
    participant list carries names for the WHOLE history, where the per-user
    Profile API only answers for recently-active people (the 0/100 run)."""
    from sqlalchemy import select, or_
    from app.models.person import Person, Identity
    from app.services.meta_send import fetch_conversation_names
    from app.core.config import settings

    names: dict = {}
    pages = list(settings.page_token_map().keys()) or [None]
    for pg in pages:
        names.update(await fetch_conversation_names(pg))
    print(f"conversation sweep: {len(names)} named participant(s) from the page inbox")
    if not names:
        return 0

    named = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Identity, Person)
            .join(Person, Person.id == Identity.person_id)
            .where(Identity.channel.in_(("messenger", "facebook", "instagram")))
            .where(or_(Person.display_name.is_(None), Person.display_name == ""))
            .where(Person.merged_into_id.is_(None))
        )).all()
        for ident, person in rows:
            name = names.get(str(ident.external_id))
            if not name:
                continue
            person.display_name = name[:200]
            if not ident.display_name:
                ident.display_name = name[:200]
            rp = dict(ident.raw_profile or {})
            rp.pop("no_profile", None)          # it's nameable after all
            ident.raw_profile = rp
            named += 1
        if named:
            await db.commit()
    print(f"conversation sweep: named {named} backlog contact(s)")
    return named


async def run(batch: int = 100, max_batches: int = 60, retry_marked: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    named = tried = 0
    named += await _sweep_conversation_names()   # phase 1: one paged sweep, no per-user calls
    for i in range(max_batches):
        async with AsyncSessionLocal() as db:
            res = await backfill_unknown_profiles(db, limit=batch, retry_marked=retry_marked)
        named += res["enriched"]
        tried += res["attempted"]
        print(f"batch {i + 1}: attempted={res['attempted']} "
              f"named={res['enriched']} no-profile={res['marked']}")
        if res["scanned"] == 0 or (retry_marked and res["enriched"] == 0):
            break                            # nothing left, or retries aren't landing
    print(f"── done: named {named} contact(s) out of {tried} tried ──")
    if tried and named == 0:
        print("NOTE: the Profile API returned NO names — check the api logs for "
              "'profile fetch … →' (likely a permissions/App-Review gap).")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Name the Unknown Meta contacts via the Profile API.")
    ap.add_argument("--retry-marked", action="store_true",
                    help="also retry contacts previously marked no-profile (run after App Review)")
    asyncio.run(run(retry_marked=ap.parse_args().retry_marked))
