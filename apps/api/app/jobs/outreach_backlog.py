"""The needs-approval pile — read it, and retire what is plainly stale.

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.outreach_backlog                 # report only
    … python -m app.jobs.outreach_backlog --retire-older-than 30      # also veto

The report: how many rows wait, by why (window, team check, language, unknown
outcome, …), by age and by kind — counts only, nothing about a customer.

`--retire-older-than N` vetoes ROUTINE rows (sales nudges nobody asked for)
that have waited more than N days, with the reason "[retired: parked N+ days —
the moment has passed]" so the record says what happened. A kept promise
(check-in on a day the customer named), care about an order (fit check,
payment reminder) and anything younger are left for a person. Nothing is sent
by this command, ever. A person on the box runs it; it is not scheduled.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone


async def _main(retire_days: int | None) -> int:
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent_action import AgentAction
    from app.services import outreach_log as ol
    from app.services.actions import message_class
    async with AsyncSessionLocal() as db:
        view = await ol.backlog_view(db)
        print(json.dumps(view, indent=1, sort_keys=True))
        if retire_days is None:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=retire_days)
        rows = (await db.execute(select(AgentAction).where(
            AgentAction.status == "needs_approval",
            AgentAction.created_at < cutoff))).scalars().all()
        n = 0
        for row in rows:
            if message_class(row) != ol.ROUTINE:
                continue                       # promises and care wait for a person
            row.status = "vetoed"
            row.reason = f"{row.reason or ''} [retired: parked {retire_days}+ days — the moment has passed]"[:1000]
            n += 1
        await db.commit()
        print(f"retired {n} routine row(s) parked more than {retire_days} days; "
              f"{len(rows) - n} older row(s) left for a person (promises, care)")
        return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--retire-older-than", type=int, default=None, metavar="DAYS",
                    help="veto routine rows parked more than DAYS days (nothing is sent)")
    args = ap.parse_args(argv)
    if args.retire_older_than is not None and args.retire_older_than < 7:
        ap.error("--retire-older-than must be at least 7 days")
    return asyncio.run(_main(args.retire_older_than))


if __name__ == "__main__":
    raise SystemExit(main())
