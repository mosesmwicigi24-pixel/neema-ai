"""Backfill transcripts for voice notes and call recordings saved before the
engine was switched on (calls & audio programme, cycle 8, 2026-10-05).

    python -m app.scripts.backfill_transcripts --dry-run  [--since 30d] [--kind all|notes|calls]
    python -m app.scripts.backfill_transcripts --execute  [--since 30d] [--max-usd 1.50] [--limit 200]

A PRODUCTION DATA WRITE when run with --execute: it fills messages.text /
transcript_* / translated_* and calls.transcript / summary / insights, and
appends call briefs to customers' CRM notes. The owner approves it first.

What it picks:
  · inbound voice notes (WhatsApp, Messenger, Instagram) since --since with
    no transcript yet — status NULL/none and the stored text still a
    placeholder ("[audio received]", empty) — or a failure that was a
    configuration problem at the time (disabled, no_provider, provider_auth)
    or transient (timeouts, 5xx, budget). Notes transcribed by the n8n era
    (words in `text`, no status) are left alone.
  · call recordings with no brief (none / recorded / failed:<non-poison>).
  Never: corrupt / too_long / too_large files (a poison file is never sent to
  a provider again), rows whose audio file is missing on disk (counted and
  listed, not written).

Files saved before 2026-10-05 have NO extension (`wa_<media id>`): the
engine decodes by content (ffmpeg probes the bytes), so they need nothing.

Cost: each file's length is read with ffmpeg first; --dry-run prints the
minutes and the estimate. --execute stops BEFORE the item that would pass the
lower of today's remaining transcription budget (TRANSCRIBE_DAILY_CAP_USD,
counted in redis) and --max-usd — rows past the cap are left untouched, never
marked over_budget — so a rerun tomorrow continues where it stopped. Items
run one at a time, newest first. Idempotent: a rerun skips what is done.
Old notes never wake the agent (no customer gets a late reply).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

POISON = ("corrupt", "too_long", "too_large")
REVISIT = ("disabled", "no_provider", "provider_auth", "provider_timeout", "provider_busy",
           "provider_unreachable", "provider_error", "provider_rejected", "error", "busy",
           "over_budget", "no_file", "analysis")


@dataclass
class Item:
    kind: str           # note | call
    key: str            # message id | call_id
    path: str | None
    seconds: float
    created: datetime | None


def parse_since(s: str) -> timedelta:
    m = re.fullmatch(r"\s*(\d+)\s*([dh])\s*", s or "")
    if not m:
        raise argparse.ArgumentTypeError("use e.g. 30d or 12h")
    n = int(m.group(1))
    return timedelta(days=n) if m.group(2) == "d" else timedelta(hours=n)


def _placeholder(text: str | None) -> bool:
    t = (text or "").strip()
    return not t or t.startswith("[") or t.startswith("(the customer sent")


def _revisit(status: str | None) -> bool:
    s = (status or "").strip()
    if s in ("", "none", "recorded", "failed"):
        return True
    if s.startswith("failed:"):
        r = s[7:]
        return r not in POISON and r in REVISIT
    return False


async def probe_seconds(path: str) -> float:
    """The audio's length from ffmpeg's header read (no decode). Falls back to
    a size estimate (opus voice ≈ 3 KB/s, rounded UP) when the header has none."""
    from app.services import transcribe as stt
    try:
        _rc, err = await stt._run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path], timeout=30)
        d = stt._DUR.search(err)
        if d:
            secs = stt._secs(d)
            if secs > 0:
                return secs
    except Exception:
        pass
    return max(1.0, os.path.getsize(path) / 3000.0)


async def find(since: timedelta, kind: str, limit: int) -> tuple[list[Item], list[str]]:
    """(items to transcribe, newest first; keys whose audio file is missing)."""
    from app.database import AsyncSessionLocal
    from app.models.call import Call
    from app.models.message import Message, MsgDirection
    from app.services import call_transcribe, voice_notes
    cutoff = datetime.now(timezone.utc) - since
    items: list[Item] = []
    missing: list[str] = []
    async with AsyncSessionLocal() as db:
        if kind in ("all", "notes"):
            rows = (await db.execute(
                select(Message).where(
                    Message.media_type == "audio", Message.direction == MsgDirection.inbound,
                    Message.media_url.is_not(None), Message.created_at >= cutoff,
                    or_(Message.transcript_status.is_(None),
                        Message.transcript_status.in_(("none", "failed")),
                        Message.transcript_status.like("failed:%")))
                .order_by(Message.created_at.desc()))).scalars().all()
            for m in rows:
                if not _revisit(m.transcript_status):
                    continue
                if m.transcript_status in (None, "none") and not _placeholder(m.text):
                    continue                     # n8n-era rows that WERE transcribed
                path = voice_notes._local_file(m.media_url)
                if not path:
                    missing.append(f"note {m.id}")
                    continue
                items.append(Item("note", str(m.id), path, 0.0, m.created_at))
        if kind in ("all", "calls"):
            rows = (await db.execute(
                select(Call).where(Call.recording_url.is_not(None), Call.started_at >= cutoff,
                                   or_(Call.transcript_status.is_(None),
                                       Call.transcript_status.in_(("none", "recorded", "failed")),
                                       Call.transcript_status.like("failed:%")))
                .order_by(Call.started_at.desc()))).scalars().all()
            for c in rows:
                if not _revisit(c.transcript_status) or c.summary:
                    continue
                path = call_transcribe._local_path(c.recording_url)
                if not path:
                    missing.append(f"call {c.call_id}")
                    continue
                items.append(Item("call", c.call_id, path, 0.0, c.started_at))
    items.sort(key=lambda i: i.created or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    items = items[:limit] if limit else items
    for it in items:
        it.seconds = await probe_seconds(it.path)
    return items, missing


async def remaining_budget(redis, max_usd: float | None) -> float:
    from app.core.config import settings
    from app.services import transcribe as stt
    cap = float(settings.transcribe_daily_cap_usd or 0)
    left = float("inf") if cap <= 0 else max(0.0, cap - await stt.spent_today(redis))
    if max_usd is not None:
        left = min(left, max_usd)
    return left


async def run(args, redis=None, out=print) -> dict:
    from app.services import transcribe as stt
    since = args.since if isinstance(args.since, timedelta) else parse_since(args.since)
    items, missing = await find(since, args.kind, args.limit)
    rate = stt.price_per_min(stt.model_for())
    total_min = sum(i.seconds for i in items) / 60.0
    budget = await remaining_budget(redis, args.max_usd)
    report = {"notes": sum(i.kind == "note" for i in items), "calls": sum(i.kind == "call" for i in items),
              "missing": len(missing), "minutes": round(total_min, 2),
              "estimate_usd": round(total_min * rate, 4), "budget_usd": budget,
              "done": 0, "results": {}, "stopped_at_cap": False}
    out(f"backfill: {report['notes']} voice notes + {report['calls']} call recordings since "
        f"{since.days}d · {report['minutes']} min ≈ ${report['estimate_usd']} "
        f"(${rate}/min, {stt.model_for()}) · budget left ${budget if budget != float('inf') else 'unlimited'}"
        f" · audio missing on disk: {len(missing)}")
    for m in missing[:20]:
        out(f"  missing: {m}")
    if not args.execute:
        out("dry run — nothing written. Re-run with --execute (owner approval) to transcribe.")
        return report
    why = stt.configured()
    if why:
        out(f"cannot run: transcription is not configured ({stt.describe('failed:' + why)})")
        report["error"] = why
        return report

    from app.services import call_transcribe, voice_notes
    spent = 0.0
    for it in items:
        cost = it.seconds / 60.0 * rate
        if spent + cost > budget + 1e-9:
            report["stopped_at_cap"] = True
            out(f"stopping before {it.kind} {it.key}: ${spent:.4f} spent of ${budget:.4f} — rerun to continue")
            break
        if it.kind == "note":
            res = await voice_notes.interpret(it.key, path=it.path, redis=redis)
        else:
            res = await call_transcribe._process(it.key)
        spent += cost
        report["done"] += 1
        report["results"][res] = report["results"].get(res, 0) + 1
        out(f"  {it.kind} {it.key}: {res} ({it.seconds:.0f}s)")
    out(f"backfill finished: {report['done']} processed, ≈${spent:.4f} · {report['results']}")
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.scripts.backfill_transcripts",
                                description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="list and estimate; write nothing")
    g.add_argument("--execute", action="store_true", help="transcribe (a production data write)")
    p.add_argument("--since", type=parse_since, default=parse_since("30d"))
    p.add_argument("--kind", choices=("all", "notes", "calls"), default="all")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--max-usd", type=float, default=None)
    args = p.parse_args(argv)

    async def go():
        import redis.asyncio as aioredis
        from app.core.config import settings
        from app.services import ai_budget
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.ping()
        except Exception:
            if args.execute:
                print("redis is unreachable — the daily budget can't be counted; refusing to --execute")
                return 2
            r = None
        ai_budget.attach(r)          # the engine's cap + meter, as in the app
        try:
            rep = await run(args, redis=r)
        finally:
            if r is not None:
                await r.aclose()
        return 1 if rep.get("error") else 0
    return asyncio.run(go())


if __name__ == "__main__":
    sys.exit(main())
