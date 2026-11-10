"""Audit, and on request repair, the names customers are shown and greeted by.

    python -m app.scripts.audit_names                    # dry run: report only
    python -m app.scripts.audit_names --apply --actor <who>   [--limit 5000]

Owner, 2026-11-09: a customer showed as "John 14:14" — a Facebook display
name that is a Bible verse. services/names now records every name with its
source and decides the canonical one; this script brings the people recorded
BEFORE that rule under it.

For every live person (not merged away) it gathers only real evidence:

  · each channel identity's display name (WhatsApp, Facebook, Instagram …)
    as that channel's profile name;
  · the user row's name — as confirmed when it was confirmed, else as the
    WhatsApp profile name (or a social profile name for a non-phone row);
  · the customer's own self-introductions in their inbound messages
    ("My name is Peter", "I'm Bishop Daniel"), the latest one winning;

and lets services/names decide. Nothing is invented: a person whose only name
is a verse, a church, a handle or a placeholder keeps it on the record and is
listed as UNRECOVERABLE (Neema simply no longer greets them by it); a name
staff confirmed is never replaced. The dry run writes nothing. --apply writes
each person's name record and mirrors the decision onto persons.display_name
and users.name / name_confirmed, one person per transaction under the row
lock, and logs who ran it. Idempotent: a second run changes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import pkgutil
import sys
from collections import Counter

from sqlalchemy import select

import app.models as _models

for _m in pkgutil.iter_modules(_models.__path__):
    importlib.import_module(f"{_models.__name__}.{_m.name}")


async def evidence(db, person) -> dict:
    """{'identities', 'users', 'stated': [(text, at)]} for one person."""
    from app.models.message import Message, MsgDirection
    from app.models.person import Identity
    from app.services.market import users_for_person
    from app.services import names
    identities = (await db.execute(select(Identity).where(
        Identity.person_id == person.id))).scalars().all()
    users = await users_for_person(db, person.id)
    rows = (await db.execute(
        select(Message.text, Message.created_at)
        .where(Message.person_id == person.id, Message.direction == MsgDirection.inbound,
               Message.text.isnot(None))
        .order_by(Message.created_at.desc()).limit(400))).all()
    stated = []
    for text, at in rows:
        n = names.self_introduction(text)
        if n:
            stated.append((n, at.isoformat(timespec="seconds") if at else None))
    return {"identities": identities, "users": users, "stated": stated}


def plan(person, ev: dict) -> dict:
    """The decision services/names reaches from the evidence alone (no write)."""
    from app.services import names
    users = ev["users"]
    u0 = users[0] if users else None
    st, _ = names.seed_from_legacy(
        {k: v for k, v in (person.state or {}).items()},
        user_name=(u0.name if u0 else None), user_confirmed=bool(u0 and u0.name_confirmed),
        person_name=person.display_name, identities=ev["identities"],
        user_wa_id=(u0.wa_id if u0 else None))
    for n, at in reversed(ev["stated"]):          # oldest first, so the latest stands
        st, _ = names.observe(st, n, by="stated", at=at)
    d = names.decide(st)
    shown = [x for x in {person.display_name, *(u.name for u in users)} if x]
    changes = bool(d) and (not shown or any(x != d["value"] for x in shown))
    return {"state": st, "decision": d, "shown": shown, "changes": changes}


def verdict(p: dict) -> str:
    d = p["decision"]
    if d is None:
        return "nameless"
    if d["kind"] != "person":
        return "unrecoverable"
    if not p["changes"]:
        return "ok"
    from app.services import names
    if any(names.classify(x) != "person" for x in p["shown"]):
        return "recovered"
    return "reconciled"


async def run(apply: bool, actor: str | None, limit: int) -> int:
    from app.database import AsyncSessionLocal
    from app.models.person import Person
    from app.services import names
    from app.services.state_lock import lock_for_write
    from sqlalchemy.orm.attributes import flag_modified

    counts: Counter = Counter()
    async with AsyncSessionLocal() as db:
        ids = (await db.execute(select(Person.id).where(Person.merged_into_id.is_(None))
                                .order_by(Person.created_at.desc()).limit(limit))).scalars().all()
    for pid in ids:
        async with AsyncSessionLocal() as db:
            person = await db.get(Person, pid)
            if person is None:
                continue
            ev = await evidence(db, person)
            p = plan(person, ev)
            v = verdict(p)
            counts[v] += 1
            if v in ("recovered", "reconciled", "unrecoverable"):
                d = p["decision"]
                print(f"{v:13} {pid}  shown={p['shown']!r} -> "
                      f"{(d or {}).get('value')!r} ({(d or {}).get('by')}, {(d or {}).get('kind')})")
            def _bare(rec):
                return {k: v for k, v in (rec or {}).items() if k != "audited"}
            unchanged = (not p["changes"]
                         and _bare(p["state"].get("name")) == _bare((person.state or {}).get("name")))
            if not apply or unchanged:
                await db.rollback()
                continue
            locked = await lock_for_write(db, person)
            if locked is None:
                await db.rollback()
                continue
            st = dict(locked.state or {})
            st["name"] = p["state"]["name"]
            if actor:
                st["name"]["audited"] = {"by": actor, "at": names._now()}
            locked.state = st
            flag_modified(locked, "state")
            names.mirror(locked, ev["users"], p["decision"])
            await db.commit()
    print("\n" + ", ".join(f"{k}: {n}" for k, n in sorted(counts.items())))
    print("APPLIED" if apply else "dry run — nothing written (use --apply --actor <who>)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the decisions (default: report only)")
    ap.add_argument("--actor", help="who ran it (required with --apply)")
    ap.add_argument("--limit", type=int, default=20000)
    a = ap.parse_args(argv)
    if a.apply and not a.actor:
        ap.error("--apply needs --actor")
    return asyncio.run(run(a.apply, a.actor, a.limit))


if __name__ == "__main__":
    sys.exit(main())
