"""One-shot dedupe: merge profiles whose evidence is OVERWHELMING.

Backfill for duplicates that predate the automatic merge paths
(capture_contact's shared-phone merge, reconcile_waref's click-through merge).

The overwhelming standard here is deliberately narrow — the SAME full phone
number (exact E.164 digits) on two live profiles, with a WhatsApp-anchored
profile to survive as primary (it can transact and be paid). Everything
softer — same email, same name, tail-only phone matches — is REPORTED for the
Merge panel's suggestion list, never auto-merged.

Usage (inside the api container):
    python -m app.jobs.dedupe_merge            # DRY RUN — prints the plan only
    python -m app.jobs.dedupe_merge --apply    # executes the merges (reversible)
"""
from __future__ import annotations

import asyncio
import re
import sys
from collections import defaultdict


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def build_plan(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pure planning from user rows:
    each row = {id, wa_id, phone, person_id, name, merged, is_wa}.

    Returns (merges, review):
      merges — [{primary, secondary, phone}] where primary is the ONE
               WhatsApp-anchored profile and secondaries share its exact digits;
      review — groups that share a phone but have no single WhatsApp anchor
               (two WhatsApp profiles can't share a wa_id, so this means
               social-only pairs) — humans decide those in the panel.
    """
    by_phone: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("merged"):
            continue
        keys = set()
        if r.get("is_wa"):
            keys.add(_digits(r.get("wa_id")))
        d = _digits(r.get("phone"))
        if len(d) >= 9:
            keys.add(d)
        for k in keys:
            if len(k) >= 9:
                by_phone[k].append(r)

    merges: list[dict] = []
    review: list[dict] = []
    seen_secondary: set[str] = set()
    for phone, group in sorted(by_phone.items()):
        persons = {r["person_id"] for r in group if r.get("person_id")}
        if len(group) < 2 or len(persons) < 2:
            continue                      # same person already — linked, not dup
        anchors = [r for r in group if r.get("is_wa")]
        others = [r for r in group
                  if not r.get("is_wa") and r["person_id"] not in {a["person_id"] for a in anchors}]
        if len(anchors) == 1 and others:
            for sec in others:
                if sec["id"] in seen_secondary:
                    continue
                seen_secondary.add(sec["id"])
                merges.append({"primary": anchors[0], "secondary": sec, "phone": phone})
        else:
            review.append({"phone": phone, "profiles": group})
    return merges, review


async def main(apply: bool) -> None:
    # Standalone script: load EVERY model module first, or SQLAlchemy's
    # string-name relationships ("Agent" on Conversation, …) fail to resolve —
    # the app normally gets this for free from the router imports in main.py.
    import importlib
    import pkgutil
    import app.models as _models
    for _m in pkgutil.iter_modules(_models.__path__):
        importlib.import_module(f"app.models.{_m.name}")

    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.models.person import Identity
    from app.services.merge import merge_persons

    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User))).scalars().all()
        # WhatsApp-anchored = has a real whatsapp identity in the spine. Digit
        # shape is NOT enough: a 15-digit Messenger PSID passes the phone
        # plausibility check and would masquerade as an anchor.
        wa_ids = {e for (e,) in (await db.execute(
            select(Identity.external_id).where(Identity.channel == "whatsapp"))).all()}
        rows = [{
            "id": str(u.id),
            "wa_id": u.wa_id,
            "phone": u.phone,
            "person_id": str(u.person_id) if u.person_id else None,
            "name": u.name,
            "merged": bool((u.state or {}).get("merged_into")),
            "is_wa": u.wa_id in wa_ids,
            "_person_uuid": u.person_id,
            "_wa_id_raw": u.wa_id,
        } for u in users]

        merges, review = build_plan(rows)

        print(f"Profiles scanned: {len(rows)}")
        print(f"Overwhelming (same exact phone, WhatsApp anchor): {len(merges)}")
        for m in merges:
            print(f"  MERGE  {m['secondary']['name'] or m['secondary']['wa_id']!r} "
                  f"({m['secondary']['wa_id']}) → "
                  f"{m['primary']['name'] or m['primary']['wa_id']!r} "
                  f"({m['primary']['wa_id']})  [phone {m['phone']}]")
        print(f"Needs a human (shared phone, no single WhatsApp anchor): {len(review)}")
        for r in review:
            who = ", ".join(f"{p['name'] or p['wa_id']}" for p in r["profiles"])
            print(f"  REVIEW [phone {r['phone']}]: {who}")

        if not apply:
            print("\nDRY RUN — nothing merged. Re-run with --apply to execute.")
            return

        done = failed = 0
        for m in merges:
            pri, sec = m["primary"], m["secondary"]
            if not pri["_person_uuid"] or not sec["_person_uuid"]:
                failed += 1
                continue
            try:
                await merge_persons(
                    db,
                    primary_person_id=pri["_person_uuid"],
                    secondary_person_id=sec["_person_uuid"],
                    primary_wa_id=pri["_wa_id_raw"],
                    secondary_wa_id=sec["_wa_id_raw"],
                )
                # Same user-row bookkeeping the CRM merge endpoint does: the
                # secondary drops out of the leads list (and out of this
                # script's next run), the primary records the union.
                from sqlalchemy.orm.attributes import flag_modified
                pri_u = (await db.execute(select(User).where(
                    User.wa_id == pri["_wa_id_raw"]))).scalar_one_or_none()
                sec_u = (await db.execute(select(User).where(
                    User.wa_id == sec["_wa_id_raw"]))).scalar_one_or_none()
                if sec_u is not None:
                    s_state = dict(sec_u.state or {})
                    s_state["merged_into"] = pri["_wa_id_raw"]
                    sec_u.state = s_state
                    flag_modified(sec_u, "state")
                if pri_u is not None:
                    p_state = dict(pri_u.state or {})
                    merged_ids = list(p_state.get("merged_ids", []))
                    if sec["_wa_id_raw"] not in merged_ids:
                        merged_ids.append(sec["_wa_id_raw"])
                    p_state["merged_ids"] = merged_ids
                    tags = set(p_state.get("tags", [])) | set(
                        (sec_u.state or {}).get("tags", []) if sec_u else [])
                    if tags:
                        p_state["tags"] = list(tags)
                    pri_u.state = p_state
                    flag_modified(pri_u, "state")
                await db.commit()
                done += 1
            except Exception as exc:
                await db.rollback()
                failed += 1
                print(f"  FAILED {sec['wa_id']} → {pri['wa_id']}: {exc}")
        print(f"\nMerged {done}; failed {failed}. Every merge is recorded in "
              f"person_merges and reversible via /unmerge.")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
