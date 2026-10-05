"""Transcription recovery (calls & audio programme, cycle 8, 2026-10-05).

Transcription runs as in-process background tasks (voice_notes.schedule,
call_transcribe.schedule_transcription). A restart, a deploy or a crash
kills them mid-flight, and nothing picked the work up again: a voice note
stayed "Transcribing…" forever (`queued` / `processing`), a call card never
got its brief. A provider outage left `failed:provider_*` rows that only a
person tapping Retry could revive, and a note refused for the day's budget
stayed refused after midnight.

sweep() finds that work and does it again — safely:

  · STUCK      queued, or processing for longer than any real run can take
               (voice: 15 min after the note arrived; calls: 90 min after the
               call ended), within the last RECOVER_DAYS. Processing rows are
               first moved back to queued by a conditional UPDATE, so two
               sweepers (two workers at startup) never both take one.
  · RETRYABLE  failed:<transient reason> (timeout, rate limit, unreachable,
               5xx, unexpected error) — at most MAX_RETRIES times per row,
               spaced by RETRY_AFTER; the count lives in redis (no redis → no
               retries of failures, only stuck rows).
  · BUDGET     failed:over_budget — retried only once today's budget has room
               again (in practice: after the UTC day rolls over).
  · NEVER      corrupt / too_long / too_large / no_file / provider_rejected /
               provider_auth / disabled / no_provider: the same file or the
               same configuration fails the same way — a poison file is never
               sent to a provider twice (the backfill command is the owner's
               explicit way to revisit config failures).

Everything goes through the normal paths (voice_notes.interpret,
call_transcribe._process), so the claim, the engine's daily ceiling, its
never-the-same-audio-twice cache and the once-per-call CRM note all hold.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update

from app.core.config import settings

_log = logging.getLogger("neema.voice")

RECOVER_DAYS = 3                       # older work is the backfill's, not the sweeper's
VOICE_STUCK_MIN = 15
CALL_STUCK_MIN = 90
MAX_RETRIES = 3
RETRY_AFTER = (timedelta(minutes=10), timedelta(hours=1), timedelta(hours=6))
TRANSIENT = ("provider_timeout", "provider_busy", "provider_unreachable", "provider_error",
             "error", "busy", "analysis", "decode_timeout")
PER_SWEEP = 50


def _reason(status: str | None) -> str | None:
    s = (status or "").strip()
    return s[7:] if s.startswith("failed:") else None


async def _retry_due(redis, kind: str, key: str, now: datetime) -> bool:
    """A failed row may be retried now: under MAX_RETRIES and past its wait.
    Records the attempt when it says yes. No redis → no."""
    if redis is None:
        return False
    rk = f"transcribe:retry:{kind}:{key}"
    try:
        raw = await redis.get(rk)
        st = json.loads(raw) if raw else {"n": 0, "next": None}
        if st["n"] >= MAX_RETRIES:
            return False
        if st.get("next") and now.timestamp() < float(st["next"]):
            return False
        wait = RETRY_AFTER[min(st["n"], len(RETRY_AFTER) - 1)]
        st = {"n": st["n"] + 1, "next": (now + wait).timestamp()}
        await redis.set(rk, json.dumps(st), ex=8 * 24 * 3600)
        return True
    except Exception:
        return False


async def _budget_room(redis) -> bool:
    from app.services import transcribe as stt
    cap = float(settings.transcribe_daily_cap_usd or 0)
    if cap <= 0:
        return True
    if redis is None:
        return False
    return await stt.spent_today(redis) < cap * 0.9


async def _eligible(redis, kind: str, key: str, status: str | None, stuck: bool, now: datetime,
                    budget_room: bool) -> bool:
    if (status or "") in ("queued", "processing", "pending"):
        # Bounded like a failure (cycle 9 audit): work that never finishes —
        # a worker killed on the same file every time — was reset and run
        # again on every sweep for RECOVER_DAYS. No redis → once per sweep,
        # as before (nothing to count with).
        if not stuck:
            return False
        return redis is None or await _retry_due(redis, f"stuck-{kind}", key, now)
    reason = _reason(status) or ("error" if status == "failed" else None)
    if reason == "over_budget":
        return budget_room                       # waits for room (the next UTC day), not a count
    if reason in TRANSIENT:
        return await _retry_due(redis, kind, key, now)
    return False


async def sweep(redis=None, *, now: datetime | None = None, limit: int = PER_SWEEP) -> dict:
    """One recovery pass. Returns counts by outcome (logs / tests). Never raises."""
    from app.database import AsyncSessionLocal
    from app.models.call import Call
    from app.models.message import Message, MsgDirection
    from app.services import transcribe as stt
    out = {"notes": 0, "calls": 0, "skipped": 0}
    if stt.configured():
        return out                               # off / no provider: nothing can succeed
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=RECOVER_DAYS)
    room = await _budget_room(redis)
    try:
        async with AsyncSessionLocal() as db:
            notes = (await db.execute(
                select(Message.id, Message.transcript_status, Message.created_at)
                .where(Message.media_type == "audio", Message.direction == MsgDirection.inbound,
                       Message.media_url.is_not(None), Message.created_at >= since,
                       or_(Message.transcript_status.in_(("queued", "processing", "pending", "failed")),
                           Message.transcript_status.like("failed:%")))
                .order_by(Message.created_at.desc()).limit(limit * 4))).all()
            calls = (await db.execute(
                select(Call.call_id, Call.transcript_status, Call.ended_at, Call.started_at)
                .where(Call.recording_url.is_not(None), Call.started_at >= since,
                       or_(Call.transcript_status.in_(("queued", "processing", "pending", "failed")),
                           Call.transcript_status.like("failed:%")))
                .order_by(Call.started_at.desc()).limit(limit * 4))).all()
    except Exception as exc:
        _log.warning("transcript recovery: listing failed: %s", exc)
        return out

    note_ids, call_ids = [], []
    for mid, status, created in notes:
        stuck = created is not None and created < now - timedelta(minutes=VOICE_STUCK_MIN)
        if len(note_ids) < limit and await _eligible(redis, "msg", str(mid), status, stuck, now, room):
            note_ids.append((mid, status))
        else:
            out["skipped"] += 1
    for cid, status, ended, started in calls:
        at = ended or started
        stuck = at is not None and at < now - timedelta(minutes=CALL_STUCK_MIN if status == "processing" else 10)
        if len(call_ids) < limit and await _eligible(redis, "call", cid, status, stuck, now, room):
            call_ids.append((cid, status))
        else:
            out["skipped"] += 1

    # Stale `processing` → `queued`, conditionally: of two sweepers, one wins.
    try:
        async with AsyncSessionLocal() as db:
            for mid, status in list(note_ids):
                if status == "processing":
                    r = await db.execute(update(Message).where(
                        Message.id == mid, Message.transcript_status == "processing")
                        .values(transcript_status="queued").returning(Message.id))
                    if r.scalar_one_or_none() is None:
                        note_ids.remove((mid, status))
            for cid, status in list(call_ids):
                if status in ("processing", "failed") or (status or "").startswith("failed:"):
                    want = "processing" if status == "processing" else status
                    r = await db.execute(update(Call).where(
                        Call.call_id == cid, Call.transcript_status == want)
                        .values(transcript_status="queued").returning(Call.call_id))
                    if r.scalar_one_or_none() is None:
                        call_ids.remove((cid, status))
            await db.commit()
    except Exception as exc:
        _log.warning("transcript recovery: reclaiming failed: %s", exc)
        return out

    from app.services import call_transcribe, voice_notes
    jobs = [voice_notes.interpret(mid, redis=redis) for mid, _ in note_ids]
    jobs += [call_transcribe._process(cid) for cid, _ in call_ids]
    if jobs:
        results = await asyncio.gather(*jobs, return_exceptions=True)
        out["notes"], out["calls"] = len(note_ids), len(call_ids)
        _log.info("transcript recovery: %d notes, %d calls → %s", len(note_ids), len(call_ids),
                  [r if isinstance(r, str) else type(r).__name__ for r in results])
    return out
