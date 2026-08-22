#!/usr/bin/env python
"""Purge the Meta user identifiers Meta asked us to delete.

Meta emails a "User Data Deletion Request" and offers a downloadable file of
app-scoped user IDs (Download User Identifiers → advanced settings; the link
expires after 60 days). Feed that file to this script.

    # see exactly what would go — changes nothing
    python scripts/purge_meta_users.py ~/Downloads/user_identifiers.csv

    # do it
    python scripts/purge_meta_users.py ~/Downloads/user_identifiers.csv --apply

Dry-run is the default and --apply is the only way to delete, because this
removes real customer history and there is no undo. IDs in the file that we
never had are simply reported as "not found" — Meta says to disregard those.

Accepts .csv, .txt or .json: any line or field that looks like an app-scoped id
is picked up, headers and blank lines ignored.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ID = re.compile(r"[A-Za-z0-9_.-]{6,128}")
_SKIP = re.compile(r"^(id|user[_ ]?id|app[_-]?scoped[_-]?id|identifier|ids)$", re.I)


def read_ids(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="ignore").strip()
    ids: list[str] = []
    if raw.startswith(("{", "[")):
        def walk(node):
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif isinstance(node, (str, int)):
                ids.append(str(node))
        walk(json.loads(raw))
    else:
        for line in raw.splitlines():
            for field in re.split(r"[,;\t]", line):
                field = field.strip().strip('"').strip("'")
                if field and not _SKIP.match(field) and _ID.fullmatch(field):
                    ids.append(field)
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description="Purge Meta user data deletion requests.")
    ap.add_argument("file", type=Path, help="the identifiers file downloaded from Meta")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default is a dry run)")
    args = ap.parse_args()

    if not args.file.exists():
        print(f"no such file: {args.file}", file=sys.stderr)
        return 2
    ids = read_ids(args.file)
    if not ids:
        print("no identifiers found in that file", file=sys.stderr)
        return 2

    from app.database import AsyncSessionLocal
    from app.services import meta_deletion as md

    totals = {"messages": 0, "conversations": 0, "identities": 0, "persons": 0}
    found, missing = 0, 0
    async with AsyncSessionLocal() as db:
        for ext in ids:
            counts = await md.purge_meta_user(db, ext, dry_run=not args.apply)
            hit = counts["messages"] or counts["conversations"] or counts["identities"]
            if hit:
                found += 1
                for k in totals:
                    totals[k] += counts[k]
                print(f"{'purged ' if args.apply else 'would purge'} {ext}: "
                      f"{counts['messages']} messages, {counts['conversations']} conversations, "
                      f"{counts['identities']} identities, {counts['persons']} persons")
                if args.apply:
                    code = md.new_confirmation_code()
                    await md.write_receipt(db, code, ext, counts)
            else:
                missing += 1
        if args.apply:
            await db.commit()

    print("\n" + ("APPLIED" if args.apply else "DRY RUN — nothing was changed"))
    print(f"identifiers in file : {len(ids)}")
    print(f"matched in Neema    : {found}")
    print(f"not in our database : {missing}   (Meta says to disregard these)")
    print(f"messages            : {totals['messages']}")
    print(f"conversations       : {totals['conversations']}")
    print(f"identities          : {totals['identities']}")
    print(f"persons removed     : {totals['persons']}"
          "   (only those left with nothing else — a customer who also uses "
          "WhatsApp keeps that history)")
    if not args.apply and found:
        print("\nre-run with --apply to carry it out")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
