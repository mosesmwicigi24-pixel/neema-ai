"""One-off re-engagement sweep: reply to customers who are waiting on us.

Selects conversations whose LAST message is an inbound (customer) text within
the last 24h — the WhatsApp / Messenger free-form messaging window, so a natural
reply is allowed — and that are in AI intercept mode (human-handled ones are
skipped). For each, Neema generates a contextual reply to that last message
using the normal agent loop and sends it on the conversation's native channel.

Deliberately MANUAL and never on a timer — an outbound campaign must be an
explicit human decision. Defaults to a dry run; pass --send to actually send:

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.reengage            # preview only
    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.reengage --send     # SEND live

Idempotent: once we reply, that conversation's last message is outbound, so a
re-run won't pick it again; a Redis guard on the last inbound message id also
prevents a double-send within/after a run.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.models.conversation import Conversation, ConvStatus, InterceptMode
from app.models.message import Message, MsgDirection

_log = logging.getLogger("neema.reengage")

CHANNELS = ("whatsapp", "messenger", "instagram")
WINDOW_HOURS = 24
_GUARD_TTL = 7 * 24 * 3600   # a conversation is re-engaged at most once a week


def _qualifies(msg: Message | None) -> bool:
    """We owe a reply iff the newest message is an inbound text from the
    customer (not our own outbound, not a text-less media/echo row)."""
    return bool(msg) and msg.direction == MsgDirection.inbound and bool((msg.text or "").strip())


async def _make_redis():
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True,
                              socket_connect_timeout=5, socket_timeout=5)
        await r.ping()
        return r
    except Exception:                      # a sweep can run without the cache
        _log.warning("redis unavailable — running without the double-send guard")
        return None


async def _latest_message(db, conv_id) -> Message | None:
    return (await db.execute(
        select(Message).where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()


async def find_waiting(db) -> list[tuple[Conversation, Message]]:
    """Open, AI-mode conversations on WhatsApp/Messenger/IG whose last message is
    a fresh (<=24h) inbound text — i.e. the customer is waiting on us."""
    cutoff = datetime.utcnow() - timedelta(hours=WINDOW_HOURS)
    convs = (await db.execute(
        select(Conversation).where(
            Conversation.channel.in_(CHANNELS),
            Conversation.intercept_mode == InterceptMode.ai,
            Conversation.status == ConvStatus.open,
            Conversation.last_message_at >= cutoff,
        ).order_by(Conversation.last_message_at.desc()))).scalars().all()
    out: list[tuple[Conversation, Message]] = []
    for conv in convs:
        msg = await _latest_message(db, conv.id)
        if _qualifies(msg):
            out.append((conv, msg))
    return out


async def _draft(redis, conv: Conversation, text: str) -> str:
    """Generate the reply Neema should send, via the normal agent loop."""
    from app.agent import runtime
    from app.agent.runtime import build_llm, route_model
    is_wa = conv.channel == "whatsapp"
    async with AsyncSessionLocal() as db:
        if is_wa:
            return await runtime.run_turn(db, redis, conv.wa_id, text,
                                          build_llm(model=route_model(text)))
        return await runtime.run_turn(db, redis, wa_id=conv.external_id, user_text=text,
                                      llm=build_llm(model=route_model(text)),
                                      channel=conv.channel, external_id=conv.external_id)


async def _handle(redis, conv: Conversation, msg: Message, *, send: bool) -> dict:
    from app.services import n8n_bridge as svc
    from app.services.meta_send import send_to_channel

    is_wa = conv.channel == "whatsapp"
    to = conv.wa_id if is_wa else conv.external_id
    text = (msg.text or "").strip()
    res = {"channel": conv.channel, "to": to, "last_in": text[:80],
           "draft": "", "sent": False, "skipped": None, "error": None}

    if is_wa and not to:                   # defensive: WhatsApp row without a number
        res["skipped"] = "no wa_id"
        return res

    # Double-send guard (only matters for a live send).
    if send and redis is not None:
        try:
            ok = await redis.set(f"reengage:{msg.id}", "1", nx=True, ex=_GUARD_TTL)
            if not ok:
                res["skipped"] = "already re-engaged"
                return res
        except Exception:
            pass                           # guard is best-effort; don't block the sweep

    try:
        reply = await _draft(redis, conv, text)
    except Exception as e:
        res["error"] = f"draft failed: {str(e)[:160]}"
        return res
    res["draft"] = (reply or "")[:200]

    if not send or not reply:
        return res

    try:
        if is_wa:
            await svc._send_waba(to, reply)
            async with AsyncSessionLocal() as db2:
                await svc.save_outbound_message(db2, redis, to, reply)
        else:
            await send_to_channel(conv.channel, to, reply)
            async with AsyncSessionLocal() as db2:
                await svc.save_outbound_channel_message(db2, redis, conv.channel, to, reply)
        res["sent"] = True
    except Exception as e:
        res["error"] = f"send failed: {str(e)[:160]}"
    return res


async def run(send: bool) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    redis = await _make_redis()
    async with AsyncSessionLocal() as db:
        waiting = await find_waiting(db)

    mode = "LIVE SEND" if send else "DRY RUN (no messages sent)"
    _log.info("── re-engage sweep · %s ─────────────────────────────", mode)
    _log.info("%d conversation(s) waiting on us (<=%dh, AI mode, WhatsApp+Meta)",
              len(waiting), WINDOW_HOURS)

    sent = failed = skipped = 0
    for conv, msg in waiting:
        r = await _handle(redis, conv, msg, send=send)
        if r["skipped"]:
            skipped += 1
            tag = f"SKIP ({r['skipped']})"
        elif r["error"]:
            failed += 1
            tag = f"FAIL — {r['error']}"
        elif r["sent"]:
            sent += 1
            tag = "SENT"
        else:
            tag = "DRAFT"
        _log.info("[%s] %-9s %s\n    last : %s\n    reply: %s",
                  tag, r["channel"], r["to"], r["last_in"], r["draft"])

    _log.info("── done: %d candidate(s) · %d sent · %d skipped · %d failed ──",
              len(waiting), sent, skipped, failed)
    if redis is not None:
        try:
            await redis.aclose()
        except Exception:
            pass
    return {"candidates": len(waiting), "sent": sent, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Re-engage customers waiting on us (<=24h).")
    ap.add_argument("--send", action="store_true",
                    help="actually send. Without this flag it only previews (dry run).")
    args = ap.parse_args()
    asyncio.run(run(send=args.send))
