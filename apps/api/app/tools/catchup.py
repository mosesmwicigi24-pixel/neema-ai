"""Catch up every enquiry the Meta outage left unanswered — once, safely.

    docker compose exec -T api python -m app.tools.catchup

Born 2026-08-19: the page token died in the morning (password change), every
Messenger/Instagram/Facebook send failed until a fresh token was installed at
~10:20 UTC. What the outage left behind, and what this clears:

  * DMs: the missed-reply sweeper found each waiting thread, composed a reply,
    failed to deliver it three times (its cost bound), and escalated to a
    human. The 3-strike counters live in redis for TWO DAYS — so even with a
    working token, the sweeper refuses those exact messages and re-escalates
    on every auto-release cycle (the "Flagged → Released to AI" ping-pong in
    the activity log). Clearing the counters lets it actually retry, and it
    only ever answers threads whose LATEST message is still the customer's.
  * Comment threads: comments are answered on capture, never swept — a
    comment whose reply failed to post has no retry path at all. This finds
    inbound comments (<24h, thread still in AI mode) with no reply threaded
    under them and runs the normal engage path — same intent gate, same
    budget guard, same free path for identified posts.

Everything is bounded, and nothing here invents a new send path: DMs go
through the sweeper, comments through the engage worker, so every guard the
system has applies here too.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(message)s")
_log = logging.getLogger("neema.catchup")

COMMENT_LIMIT = 60          # one run answers at most this many comments
SWEEP_PASSES = 10           # sweeper passes (each bounded to 20 threads)


async def _clear_strikes(redis) -> int:
    """Drop the outage's burnt 3-strike counters (and stale pacing locks) so
    the sweeper judges each thread afresh, now that sends work again."""
    n = 0
    for pattern in ("agent:missed:tries:*", "agent:missed:lock:*"):
        try:
            async for key in redis.scan_iter(match=pattern, count=200):
                await redis.delete(key)
                n += 1
        except Exception as exc:
            _log.warning("clearing %s failed: %s", pattern, exc)
    return n


async def _release_flag_escalations(db) -> int:
    """Return outage-escalated threads to the AI *now* instead of waiting for
    the 45-minute auto-release. Only threads NO ONE picked up: an escalation
    flags the conversation into human mode without assigning an agent, while a
    real pickup always assigns — so `assigned_agent_id IS NULL` is exactly the
    set the team never touched. Paused threads are a human's decision; left."""
    from app.models.conversation import Conversation, InterceptMode
    rows = (await db.execute(select(Conversation).where(
        Conversation.channel.in_(("messenger", "instagram", "facebook")),
        Conversation.intercept_mode == InterceptMode.human,
        Conversation.assigned_agent_id.is_(None),
    ))).scalars().all()
    for conv in rows:
        conv.intercept_mode = InterceptMode.ai
    if rows:
        await db.commit()
    return len(rows)


async def _pending_comments(db, *, max_age_h: int = 24) -> list[tuple]:
    """Inbound comments (<max_age_h, thread in AI mode) with no reply threaded
    under them. Returns (message, conversation) pairs, oldest first — answering
    in arrival order, the way a person would."""
    from app.models.conversation import Conversation, InterceptMode
    from app.models.message import Message, MsgDirection
    since = datetime.now(timezone.utc) - timedelta(hours=max_age_h)
    rows = (await db.execute(
        select(Message, Conversation)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.channel.in_(("facebook", "instagram")),
               Message.direction == MsgDirection.inbound,
               Message.comment_context.isnot(None),
               Message.waba_msg_id.isnot(None),
               Message.created_at > since,
               Conversation.intercept_mode == InterceptMode.ai)
        .order_by(Message.created_at.asc())
    )).all()
    if not rows:
        return []
    # Which comment ids already have a reply threaded under them? Outbound
    # comment replies carry comment_context={"reply_to": <comment id>}.
    conv_ids = {c.id for _, c in rows}
    answered: set[str] = set()
    for m in (await db.execute(
        select(Message).where(Message.conversation_id.in_(conv_ids),
                              Message.direction == MsgDirection.outbound,
                              Message.comment_context.isnot(None))
    )).scalars().all():
        rt = (m.comment_context or {}).get("reply_to")
        if rt:
            answered.add(str(rt))
    return [(m, c) for m, c in rows if str(m.waba_msg_id) not in answered]


async def _answer_comments(redis, pending) -> int:
    """Run the normal engage path for each unanswered comment, sequentially —
    the same intent gate, spend guard and reply shape a live comment gets."""
    from app.agent.runtime import _run_comment_engage
    from app.core.config import settings
    from app.database import AsyncSessionLocal
    from app.models.person import Identity, Person

    own_pages = {p.strip() for p in (settings.meta_page_id or "").split(",") if p.strip()}
    sent = 0
    for msg, conv in pending[:COMMENT_LIMIT]:
        # Rebuild what the webhook knew at capture time from what it stored.
        name, page_id = "", None
        try:
            async with AsyncSessionLocal() as db:
                ident = (await db.execute(select(Identity).where(
                    Identity.channel == msg.channel,
                    Identity.external_id == msg.external_id))).scalars().first()
                page_id = (getattr(ident, "raw_profile", None) or {}).get("page_id")
                if ident and ident.person_id:
                    person = await db.get(Person, ident.person_id)
                    name = (getattr(person, "display_name", None) or "")
        except Exception:
            pass
        ctx = msg.comment_context or {}
        comment = {
            "comment_id": str(msg.waba_msg_id),
            "from_id": msg.external_id,
            "from_name": name,
            "text": msg.text or "",
            "post_id": ctx.get("post_id") or "",
            "page_id": page_id,
            "post_context": ctx,
        }
        try:
            await _run_comment_engage(redis, msg.channel, comment, own_pages)
            sent += 1
            _log.info("  answered %s comment %s (%s: %r)", msg.channel,
                      comment["comment_id"], name or msg.external_id,
                      (msg.text or "")[:60])
        except Exception as exc:
            _log.warning("  comment %s failed: %s", comment["comment_id"], exc)
        await asyncio.sleep(1.5)          # gentle on Graph, on the model, on the budget
    return sent


async def main() -> None:
    import redis.asyncio as aioredis
    import app.main  # noqa: F401 — registers models/relationships
    from app.core.config import settings
    from app.database import AsyncSessionLocal
    from app.services.reply_sweeper import sweep_missed_replies

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        cleared = await _clear_strikes(redis)
        _log.info("cleared %d strike/lock key(s) from the outage", cleared)

        async with AsyncSessionLocal() as db:
            released = await _release_flag_escalations(db)
        _log.info("returned %d flag-escalated thread(s) to the AI", released)

        dm_total = 0
        for _ in range(SWEEP_PASSES):
            n = await sweep_missed_replies(redis)
            dm_total += n
            if n == 0:
                break
            await asyncio.sleep(2)
        _log.info("DM catch-up: %d repl(y/ies) delivered", dm_total)

        async with AsyncSessionLocal() as db:
            pending = await _pending_comments(db)
        _log.info("comment catch-up: %d unanswered comment(s) under 24h", len(pending))
        if len(pending) > COMMENT_LIMIT:
            _log.info("  (answering the oldest %d this run — run again for the rest)",
                      COMMENT_LIMIT)
        answered = await _answer_comments(redis, pending)

        _log.info("")
        _log.info("done: %d DM(s) answered, %d comment(s) engaged, "
                  "%d thread(s) back with the AI", dm_total, answered, released)
        _log.info("anything still unanswered is outside Meta's send window or "
                  "held by a human on purpose — it stays with the team.")
    finally:
        try:
            await redis.aclose()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
