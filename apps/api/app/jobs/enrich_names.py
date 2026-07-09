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


async def run(batch: int = 100, max_batches: int = 60) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    named = tried = 0
    for i in range(max_batches):
        async with AsyncSessionLocal() as db:
            res = await backfill_unknown_profiles(db, limit=batch)
        named += res["enriched"]
        tried += res["attempted"]
        print(f"batch {i + 1}: attempted={res['attempted']} "
              f"named={res['enriched']} no-profile={res['marked']}")
        if res["scanned"] == 0:          # nothing nameless-and-untried left
            break
    print(f"── done: named {named} contact(s) out of {tried} tried ──")
    if tried and named == 0:
        print("NOTE: the Profile API returned NO names — check the api logs for "
              "'profile fetch … →' (likely a permissions/App-Review gap).")


if __name__ == "__main__":
    asyncio.run(run())
